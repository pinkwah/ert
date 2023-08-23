#include <algorithm>
#include <filesystem>
#include <fstream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <iostream>
#include <pthread.h>
#include <unistd.h>

#include <ert/except.hpp>
#include <ert/logging.hpp>
#include <ert/res_util/string.hpp>
#include <ert/util/hash.hpp>
#include <ert/util/util.hpp>

#include <ert/job_queue/lsf_driver.hpp>
#include <ert/job_queue/lsf_job_stat.hpp>
#include <ert/job_queue/queue_driver.hpp>
#include <ert/job_queue/spawn.hpp>

namespace fs = std::filesystem;
static auto logger = ert::get_logger("job_queue.lsf_driver");

#define LSF_JSON "lsf_info.json"

/*
   Documentation/examples of programming towards the lsf libraries can
   be found in /prog/LSF/7.0/misc/examples
*/

/*
  How to call the lsf commands bsub/bjobs/bkill:
  ----------------------------------------------

  The commands to submit, monitor and modify LSF jobs are available
  through library calls through the lsf library. This is a good
  solution which works well.

  Unfortunately only quite few of the workstations in Equinor are
  "designated LSF machines", meaning that they are allowed to talk to
  the LIM servers, to be able to use the low-level lsb_xxx() function
  calls the host making the calls must configured (by an LSF
  administrator) to be a LSF client.

  The lsf_driver can either make use of the proper lsf library calls
  (lsb_submit(), lsb_openjobinfo(), ...) or alternatively it can issue
  ssh calls to an external LSF_SERVER and call up the bsub/bkill/bjob
  executables on the remote server.

  All the functions with 'library' in the name are based on library
  calls, and the functions with 'shell' in the name are based on
  external functions (the actual calls are through the
  spawn() function).

  By default the driver will use the library, but if a value is
  provided with the LSF_SERVER option, the shell based functions will
  be used. Internally this is goverened by the boolean flag
  'use_library_calls'.

  Even though you only intend to submit through the shell commands
  bsub / bjobs / bkill the build process still requires access to the
  lsf headers and the lsf library; that is probably not optimal.


  Remote login shell
  ------------------

  When submitting with LSF the job will inherit the current
  environment on the submitting host, and not read the users login
  files on the remote host where the job is actually executed. E.g. in
  situations where submitting host and executing host are
  e.g. different operating system versions this might be
  unfortunate. The '-L @shell' switch can used with bsub to force lsf
  to source schell specific input files prior to executing your
  job. This can be achieved with the LSF_LOGIN_SHELL option:

     lsf_driver_set_option( driver , LSF_LOGIN_SHELL , "csh" );

*/

#define MAX_ERROR_COUNT 100
#define SUBMIT_ERROR_SLEEP 2
#define BJOBS_REFRESH_TIME "10"
#define DEFAULT_RSH_CMD "ssh"
#define DEFAULT_BSUB_CMD "bsub"
#define DEFAULT_BJOBS_CMD "bjobs"
#define DEFAULT_BKILL_CMD "bkill"
#define DEFAULT_BHIST_CMD "bhist"

struct lsf_job_struct {
    long int lsf_jobnr;
    int num_exec_host;
    char **exec_host;
    /** Used to look up the job status in the bjobs_cache hash table */
    char *lsf_jobnr_char;
    char *job_name;
};

struct lsf_driver_struct {
    char *queue_name;
    char *resource_request;
    std::vector<std::string> exclude_hosts;
    char *login_shell;
    char *project_code;
    pthread_mutex_t submit_lock;

    lsf_submit_method_enum submit_method;
    int submit_sleep;

    int error_count;
    int max_error_count;
    int submit_error_sleep;

    /*-----------------------------------------------------------------*/
    /* Fields used by the shell based functions */
    bool debug_output;
    int bjobs_refresh_interval;
    time_t last_bjobs_update;
    /** A hash table of all jobs submitted by this ERT instance - to ensure
     * that we do not check status of old jobs in e.g. ZOMBIE status. */
    hash_type *my_jobs;
    /** The output of calling bjobs is cached in this table. */
    hash_type *bjobs_cache;
    /** Only one thread should update the bjobs_chache table. */
    pthread_mutex_t bjobs_mutex;
    char *remote_lsf_server;
    char *rsh_cmd;
    char *bsub_cmd;
    char *bjobs_cmd;
    char *bkill_cmd;
    char *bhist_cmd;
};

const std::map<const std::string, int> status_map = {
    {"PEND", JOB_STAT_PEND},   {"SSUSP", JOB_STAT_SSUSP},
    {"PSUSP", JOB_STAT_PSUSP}, {"USUSP", JOB_STAT_USUSP},
    {"RUN", JOB_STAT_RUN},     {"EXIT", JOB_STAT_EXIT},
    {"ZOMBI", JOB_STAT_EXIT},  {"DONE", JOB_STAT_DONE},
    {"PDONE", JOB_STAT_PDONE}, {"UNKWN", JOB_STAT_UNKWN}};

const std::map<const int, const job_status_type> convert_status_map = {
    {JOB_STAT_NULL, JOB_QUEUE_NOT_ACTIVE},
    {JOB_STAT_PEND, JOB_QUEUE_PENDING},
    {JOB_STAT_SSUSP, JOB_QUEUE_RUNNING},
    {JOB_STAT_USUSP, JOB_QUEUE_RUNNING},
    {JOB_STAT_PSUSP, JOB_QUEUE_RUNNING},
    {JOB_STAT_RUN, JOB_QUEUE_RUNNING},
    {JOB_STAT_DONE, JOB_QUEUE_DONE},
    {JOB_STAT_EXIT, JOB_QUEUE_EXIT},
    {JOB_STAT_UNKWN, JOB_QUEUE_UNKNOWN},
    {(JOB_STAT_DONE + JOB_STAT_PDONE), JOB_QUEUE_DONE},
    {JOB_STAT_NULL, JOB_QUEUE_NOT_ACTIVE},
    {JOB_STAT_NULL, JOB_QUEUE_NOT_ACTIVE},
    {JOB_STAT_NULL, JOB_QUEUE_NOT_ACTIVE},
};

static lsf_job_type *lsf_job_alloc(const char *job_name) {
    lsf_job_type *job;
    job = (lsf_job_type *)util_malloc(sizeof *job);
    job->num_exec_host = 0;
    job->exec_host = NULL;

    job->lsf_jobnr = 0;
    job->lsf_jobnr_char = NULL;
    job->job_name = util_alloc_string_copy(job_name);
    return job;
}

void lsf_job_free(lsf_job_type *job) {
    free(job->lsf_jobnr_char);
    util_free_stringlist(job->exec_host, job->num_exec_host);
    free(job->job_name);
    free(job);
}

int lsf_job_parse_bsub_stdout(const char *bsub_cmd, const char *stdout_file) {
    int jobid = 0;
    if ((fs::exists(stdout_file)) && (util_file_size(stdout_file) > 0)) {
        FILE *stream = util_fopen(stdout_file, "r");
        if (util_fseek_string(stream, "<", true, true)) {
            char *jobid_string = util_fscanf_alloc_upto(stream, ">", false);
            if (jobid_string != NULL) {
                util_sscanf_int(jobid_string, &jobid);
                free(jobid_string);
            }
        }
        fclose(stream);

        if (jobid == 0) {
            std::ifstream ifs(stdout_file);
            fmt::print(stderr, "Failed to get lsf job id from file: {}\n",
                       stdout_file);
            fmt::print(stderr, "bsub command                      : {}\n",
                       bsub_cmd);
            fmt::print(stderr, "{}\n", ifs);
            util_abort("%s: \n", __func__);
        }
    }
    return jobid;
}

static void lsf_driver_internal_error(const lsf_driver_type *driver) {
    auto eprint = [](auto f) { fmt::print(stderr, f); };

    eprint("\n\n");
    eprint("******************************************************\n");
    eprint("The LSF driver can be configured and used in many     \n");
    eprint("different ways. Its important how we choose to submit:\n");
    eprint("                                                      \n");
    eprint("  1. Using the lsf library calls                      \n");
    eprint("  2. Using the bsub/bjobs/bkill commands locally      \n");
    eprint("                                                      \n");
    eprint("To chose between these alternatives you set the remote\n");
    eprint("server with the lsf_driver_set_option() function.     \n");
    eprint("Passing the value NULL will give alternative 1,       \n");
    eprint("passing the special string " LOCAL_LSF_SERVER "       \n");
    eprint("will give alternative 2, and any other value will     \n");
    eprint("submit through that host using ssh.                   \n");
    eprint("                                                      \n");
    eprint("******************************************************\n");
    logger->error("In lsf_driver, attempt at submitting without setting a "
                  "value for LSF_SERVER.");
    exit(1);
}

static void lsf_driver_assert_submit_method(const lsf_driver_type *driver) {
    if (driver->submit_method == LSF_SUBMIT_INVALID) {
        lsf_driver_internal_error(driver);
    }
}

/**
  A resource string can be "span[host=1] select[A && B] bla[xyz]".
  The blacklisting feature is to have select[hname!=bad1 && hname!=bad2].

  This function injects additional "hname!=node1 && ... && hname!=node2" into
  the select[..] clause.  This addition is the result of '&&'.join(select_list).
*/
char *
alloc_composed_resource_request(const lsf_driver_type *driver,
                                const std::vector<std::string> &select_list) {
    char *resreq = util_alloc_string_copy(driver->resource_request);
    std::string excludes_string = ert::join(select_list, " && ");

    char *req = NULL;
    char *pos = strstr(resreq, "select["); // find select[...]

    if (pos == NULL) {
        // no select string in request, add select[...]
        req = util_alloc_sprintf("%s select[%s]", resreq,
                                 excludes_string.c_str());
    } else {
        // add select string to existing select[...]
        char *endpos = strstr(pos, "]");
        if (endpos != NULL)
            *endpos = ' ';
        else
            util_abort("%s could not find termination of select statement: %s",
                       __func__, resreq);

        // We split string into (before) "bla[..] bla[..] select[xxx_"
        // and (after) "... bla[..] bla[..]". (we replaced one ']' with ' ')
        // Then we make final string:  before + &&excludes] + after
        int before_size = endpos - resreq;
        char *before =
            (char *)util_alloc_substring_copy(resreq, 0, before_size);
        char *after = (char *)util_alloc_string_copy(&resreq[before_size]);

        req = util_alloc_sprintf("%s && %s]%s", before, excludes_string.c_str(),
                                 after);
    }
    free(resreq);
    return req;
}

/**
  The resource request string contains spaces, and when passed
  through the shell it must be protected with \"..\"; this applies
  when submitting to a remote lsf server with ssh. However when
  submitting to the local workstation using a bsub command the
  command will be invoked with the spawn() command - and no
  shell is involved. In this latter case we must avoid the \"...\"
  quoting.
*/
static char *alloc_quoted_resource_string(const lsf_driver_type *driver) {
    char *req = NULL;
    if (driver->exclude_hosts.size() == 0) {
        if (driver->resource_request)
            req = util_alloc_string_copy(driver->resource_request);
    } else {
        std::vector<std::string> select_list;
        for (const auto &host : driver->exclude_hosts) {
            std::string exclude_host = "hname!='" + host + "'";
            select_list.push_back(exclude_host);
        }

        // select_list is non-empty
        if (driver->resource_request != NULL) {
            req = alloc_composed_resource_request(driver, select_list);
        } else {
            std::string select_string = ert::join(select_list, " && ");
            req = util_alloc_sprintf("select[%s]", select_string.c_str());
        }
    }

    char *quoted_resource_request = NULL;
    if (req) {
        if (driver->submit_method == LSF_SUBMIT_REMOTE_SHELL)
            quoted_resource_request = util_alloc_sprintf("\"%s\"", req);
        else
            quoted_resource_request = util_alloc_string_copy(req);
        free(req);
    }
    return quoted_resource_request;
}

stringlist_type *lsf_driver_alloc_cmd(lsf_driver_type *driver,
                                      const char *lsf_stdout,
                                      const char *job_name,
                                      const char *submit_cmd, int num_cpu,
                                      int job_argc, const char **job_argv) {

    stringlist_type *argv = stringlist_alloc_new();
    char *num_cpu_string = (char *)util_alloc_sprintf("%d", num_cpu);

    char *quoted_resource_request = alloc_quoted_resource_string(driver);

    if (driver->submit_method == LSF_SUBMIT_REMOTE_SHELL)
        stringlist_append_copy(argv, driver->bsub_cmd);

    stringlist_append_copy(argv, "-o");
    stringlist_append_copy(argv, lsf_stdout);
    if (driver->queue_name != NULL) {
        stringlist_append_copy(argv, "-q");
        stringlist_append_copy(argv, driver->queue_name);
    }
    stringlist_append_copy(argv, "-J");
    stringlist_append_copy(argv, job_name);
    stringlist_append_copy(argv, "-n");
    stringlist_append_copy(argv, num_cpu_string);

    if (quoted_resource_request != NULL) {
        stringlist_append_copy(argv, "-R");
        stringlist_append_copy(argv, quoted_resource_request);
    }

    if (driver->login_shell != NULL) {
        stringlist_append_copy(argv, "-L");
        stringlist_append_copy(argv, driver->login_shell);
    }

    if (driver->project_code) {
        stringlist_append_copy(argv, "-P");
        stringlist_append_copy(argv, driver->project_code);
    }

    stringlist_append_copy(argv, submit_cmd);
    for (int iarg = 0; iarg < job_argc; iarg++)
        stringlist_append_copy(argv, job_argv[iarg]);

    free(num_cpu_string);
    free(quoted_resource_request);
    return argv;
}

static int lsf_driver_submit_shell_job(lsf_driver_type *driver,
                                       const char *lsf_stdout,
                                       const char *job_name,
                                       const char *submit_cmd, int num_cpu,
                                       int job_argc, const char **job_argv) {
    int job_id;
    char *tmp_file = (char *)util_alloc_tmp_file("/tmp", "enkf-submit", true);

    {
        stringlist_type *remote_argv =
            lsf_driver_alloc_cmd(driver, lsf_stdout, job_name, submit_cmd,
                                 num_cpu, job_argc, job_argv);

        if (driver->submit_method == LSF_SUBMIT_REMOTE_SHELL) {
            char **argv = (char **)util_calloc(2, sizeof *argv);
            argv[0] = driver->remote_lsf_server;
            argv[1] = stringlist_alloc_joined_string(remote_argv, " ");

            if (driver->debug_output)
                printf("Submitting: %s %s %s \n", driver->rsh_cmd, argv[0],
                       argv[1]);
            logger->debug("Submitting: {} {} {} \n", driver->rsh_cmd, argv[0],
                          argv[1]);

            spawn_blocking(driver->rsh_cmd, 2, (const char **)argv, tmp_file,
                           NULL);

            free(argv[1]);
            free(argv);
        } else if (driver->submit_method == LSF_SUBMIT_LOCAL_SHELL) {
            char **argv = stringlist_alloc_char_ref(remote_argv);

            if (driver->debug_output) {
                printf("Submitting: %s ", driver->bsub_cmd);
                stringlist_fprintf(remote_argv, " ", stdout);
                printf("\n");
            }
            spawn_blocking(driver->bsub_cmd, stringlist_get_size(remote_argv),
                           (const char **)argv, tmp_file, tmp_file);
            free(argv);
        }

        stringlist_free(remote_argv);
    }

    job_id = lsf_job_parse_bsub_stdout(driver->bsub_cmd, tmp_file);
    util_unlink_existing(tmp_file);
    free(tmp_file);
    return job_id;
}

static void lsf_driver_update_bjobs_table(lsf_driver_type *driver) {
    char *tmp_file = (char *)util_alloc_tmp_file("/tmp", "enkf-bjobs", true);

    if (driver->submit_method == LSF_SUBMIT_REMOTE_SHELL) {
        char **argv = (char **)util_calloc(2, sizeof *argv);
        argv[0] = driver->remote_lsf_server;
        argv[1] = util_alloc_sprintf("%s -a", driver->bjobs_cmd);
        spawn_blocking(driver->rsh_cmd, 2, (const char **)argv, tmp_file, NULL);
        free(argv[1]);
        free(argv);
    } else if (driver->submit_method == LSF_SUBMIT_LOCAL_SHELL) {
        const char **argv = (const char **)util_calloc(1, sizeof *argv);
        argv[0] = "-a";
        spawn_blocking(driver->bjobs_cmd, 1, (const char **)argv, tmp_file,
                       NULL);
        free(argv);
    }

    {
        char user[32];
        char status[16];
        FILE *stream = util_fopen(tmp_file, "r");
        bool at_eof = false;
        hash_clear(driver->bjobs_cache);
        util_fskip_lines(stream, 1);
        while (!at_eof) {
            char *line = util_fscanf_alloc_line(stream, &at_eof);
            if (line != NULL) {
                int job_id_int;

                if (sscanf(line, "%d %s %s", &job_id_int, user, status) == 3) {
                    char *job_id = (char *)util_alloc_sprintf("%d", job_id_int);
                    // Consider only jobs submitted by this ERT instance - not
                    // old jobs lying around from the same user.
                    if (hash_has_key(driver->my_jobs, job_id))
                        if (auto found_status = status_map.find(status);
                            found_status != status_map.end())
                            hash_insert_int(driver->bjobs_cache, job_id,
                                            found_status->second);
                        else {
                            util_exit("The lsf_status:%s  for job:%s is not "
                                      "recognized; call your "
                                      "LSF administrator - sorry :-( \n",
                                      status, job_id);
                        }

                    free(job_id);
                }
                free(line);
            }
        }
        fclose(stream);
    }
    util_unlink_existing(tmp_file);
    free(tmp_file);
}

static bool lsf_driver_run_bhist(lsf_driver_type *driver, lsf_job_type *job,
                                 int *pend_time, int *run_time) {
    bool bhist_ok = true;
    char *output_file = (char *)util_alloc_tmp_file("/tmp", "bhist", true);

    if (driver->submit_method == LSF_SUBMIT_REMOTE_SHELL) {
        char **argv = (char **)util_calloc(2, sizeof *argv);
        argv[0] = driver->remote_lsf_server;
        argv[1] =
            util_alloc_sprintf("%s %s", driver->bhist_cmd, job->lsf_jobnr_char);
        spawn_blocking(driver->rsh_cmd, 2, (const char **)argv, output_file,
                       NULL);
        free(argv[1]);
        free(argv);
    } else if (driver->submit_method == LSF_SUBMIT_LOCAL_SHELL) {
        char **argv = (char **)util_calloc(1, sizeof *argv);
        argv[0] = job->lsf_jobnr_char;
        spawn_blocking(driver->bjobs_cmd, 2, (const char **)argv, output_file,
                       NULL);
        free(argv);
    }

    {
        char job_id[16], user[32], job_name[32];
        int psusp_time;

        FILE *stream = util_fopen(output_file, "r");
        util_fskip_lines(stream, 2);

        if (fscanf(stream, "%s %s %s %d %d %d", job_id, user, job_name,
                   pend_time, &psusp_time, run_time) != 6)
            bhist_ok = false;

        fclose(stream);
    }
    util_unlink_existing(output_file);
    free(output_file);

    return bhist_ok;
}

/**
  When a job has completed you can query the status using the bjobs
  command for a while, and then the job will be evicted from the LSF
  status table. If there have been connection problems with the LSF
  server we can risk a situation where a job has completed and
  subsequently evicted from the LSF status table, before we are able
  to record the DONE/EXIT status.

  When a job is missing from the bjobs_cache table we as a last resort
  invoke the bhist command (which is based on internal LSF data with
  much longer lifetime) and measure the change in run_time and
  pend_time between two subsequent calls:


    1. ((pend_time1 == pend_time2) && (run_time1 == run_time2)) :
       Nothing is happening, and we assume that the job is DONE (this
       method can not distinguish between DONE and EXIT).

    2. (run_time2 > run_time1) : The job is running.

    3. (pend_tim2 > pend_time1) : The job is pending.

    4. Status unknown - have not got a clue?!
*/
static int lsf_driver_get_bhist_status_shell(lsf_driver_type *driver,
                                             lsf_job_type *job) {
    int status = JOB_STAT_UNKWN;
    int sleep_time = 4;
    int run_time1, run_time2, pend_time1, pend_time2;

    logger->error(
        "** Warning: could not find status of job:{}/{} using \'bjobs\'"
        " - trying with \'bhist\'.\n",
        job->lsf_jobnr_char, job->job_name);
    if (!lsf_driver_run_bhist(driver, job, &pend_time1, &run_time1))
        return status;

    sleep(sleep_time);
    if (!lsf_driver_run_bhist(driver, job, &pend_time2, &run_time2))
        return status;

    if ((run_time1 == run_time2) && (pend_time1 == pend_time2))
        status = JOB_STAT_DONE;

    if (pend_time2 > pend_time1)
        status = JOB_STAT_PEND;

    if (run_time2 > run_time1)
        status = JOB_STAT_RUN;

    return status;
}

static int lsf_driver_get_job_status_shell(void *__driver, void *__job) {
    int status = JOB_STAT_NULL;

    if (__job != NULL) {
        auto job = static_cast<lsf_job_type *>(__job);
        auto driver = static_cast<lsf_driver_type *>(__driver);

        {
            // Updating the bjobs_table of the driver involves a significant
            // change in the internal state of the driver; that is semantically
            // a bit unfortunate because this is clearly a get() function; to
            // protect against concurrent updates of this table we use a mutex.
            pthread_mutex_lock(&driver->bjobs_mutex);
            {
                bool update_cache =
                    ((difftime(time(NULL), driver->last_bjobs_update) >
                      driver->bjobs_refresh_interval) ||
                     (!hash_has_key(driver->bjobs_cache, job->lsf_jobnr_char)));
                if (update_cache) {
                    lsf_driver_update_bjobs_table(driver);
                    driver->last_bjobs_update = time(NULL);
                }
            }
            pthread_mutex_unlock(&driver->bjobs_mutex);

            if (hash_has_key(driver->bjobs_cache, job->lsf_jobnr_char))
                status = hash_get_int(driver->bjobs_cache, job->lsf_jobnr_char);
            else {
                // The job was not in the status cache, this *might* mean that
                // it has completed/exited and fallen out of the bjobs status
                // table maintained by LSF. We try calling bhist to get the
                // status.
                logger->warning(
                    "In lsf_driver we found that job was not in the "
                    "status cache, this *might* mean that it has "
                    "completed/exited and fallen out of the bjobs "
                    "status table maintained by LSF.");
                if (!driver->debug_output) {
                    driver->debug_output = true;
                    logger->info("Have turned lsf debug info ON.");
                }
                status = lsf_driver_get_bhist_status_shell(driver, job);
                hash_insert_int(driver->bjobs_cache, job->lsf_jobnr_char,
                                status);
            }
        }
    }

    return status;
}

job_status_type lsf_driver_convert_status(int lsf_status) {
    job_status_type job_status = JOB_QUEUE_NOT_ACTIVE;

    if (auto found_status = convert_status_map.find(lsf_status);
        found_status != convert_status_map.end())
        job_status = found_status->second;
    else
        throw exc::runtime_error("%s: unrecognized lsf status code:%d \n",
                                 __func__, lsf_status);

    return job_status;
}

int lsf_driver_get_job_status_lsf(void *__driver, void *__job) {
    int lsf_status;
    auto driver = static_cast<lsf_driver_type *>(__driver);

    return lsf_driver_get_job_status_shell(__driver, __job);
}

job_status_type lsf_driver_get_job_status(void *__driver, void *__job) {
    int lsf_status = lsf_driver_get_job_status_lsf(__driver, __job);
    return lsf_driver_convert_status(lsf_status);
}

void lsf_driver_free_job(void *__job) {
    auto job = static_cast<lsf_job_type *>(__job);
    lsf_job_free(job);
}

/**
 * Parses the given file containing colon separated hostnames, ie.
 * "hname1:hname2:hname3".
 */
namespace detail {
std::vector<std::string> parse_hostnames(const char *fname) {
    std::ifstream stream(fname);

    std::string line;
    if (std::getline(stream, line)) { //just read the first line
        std::vector<std::string> hosts;

        // bjobs uses : as delimiter
        ert::split(line, ':', [&](auto host) {
            // Get everything after '*'. bjobs use the syntax 'N*hostname' where
            // N is an integer, specifying how many jobs should be assigned to
            // 'hostname'
            hosts.emplace_back(ert::back_element(host, '*'));
        });
        return hosts;
    }
    return {};
}
} // namespace detail

void lsf_driver_kill_job(void *__driver, void *__job) {
    auto driver = static_cast<lsf_driver_type *>(__driver);
    auto job = static_cast<lsf_job_type *>(__job);
    if (driver->submit_method == LSF_SUBMIT_REMOTE_SHELL) {
        char **argv = (char **)util_calloc(2, sizeof *argv);
        argv[0] = driver->remote_lsf_server;
        argv[1] =
            util_alloc_sprintf("%s %s", driver->bkill_cmd, job->lsf_jobnr_char);

        spawn_blocking(driver->rsh_cmd, 2, (const char **)argv, NULL, NULL);

        free(argv[1]);
        free(argv);
    } else if (driver->submit_method == LSF_SUBMIT_LOCAL_SHELL) {
        spawn_blocking(driver->bkill_cmd, 1,
                       (const char **)&job->lsf_jobnr_char, NULL, NULL);
    }
}

void *lsf_driver_submit_job(void *__driver, const char *submit_cmd, int num_cpu,
                            const char *run_path, const char *job_name,
                            int argc, const char **argv) {
    auto driver = static_cast<lsf_driver_type *>(__driver);
    lsf_driver_assert_submit_method(driver);
    {
        lsf_job_type *job = lsf_job_alloc(job_name);
        usleep(driver->submit_sleep);

        {
            char *lsf_stdout =
                (char *)util_alloc_filename(run_path, job_name, "LSF-stdout");
            lsf_submit_method_enum submit_method = driver->submit_method;
            pthread_mutex_lock(&driver->submit_lock);

            logger->info("LSF DRIVER submitting using method:{} \n",
                         submit_method);

            job->lsf_jobnr = lsf_driver_submit_shell_job(
                driver, lsf_stdout, job_name, submit_cmd, num_cpu, argc, argv);
            job->lsf_jobnr_char = util_alloc_sprintf("%ld", job->lsf_jobnr);
            hash_insert_ref(driver->my_jobs, job->lsf_jobnr_char, NULL);

            pthread_mutex_unlock(&driver->submit_lock);
            free(lsf_stdout);
        }

        if (job->lsf_jobnr > 0) {
            char *json_file =
                (char *)util_alloc_filename(run_path, LSF_JSON, NULL);
            FILE *stream = util_fopen(json_file, "w");
            fprintf(stream, "{\"job_id\" : %ld}\n", job->lsf_jobnr);
            free(json_file);
            fclose(stream);
            return job;
        } else {
            // The submit failed - the queue system shall handle
            // NULL return values.
            driver->error_count++;

            if (driver->error_count >= driver->max_error_count)
                util_exit(
                    "Maximum number of submit errors exceeded - giving up\n");
            else {
                logger->error("** ERROR ** Failed when submitting to LSF - "
                              "will try again.");
                if (!driver->debug_output) {
                    driver->debug_output = true;
                    logger->info("Have turned lsf debug info ON.");
                }
                usleep(driver->submit_error_sleep);
            }

            lsf_job_free(job);
            return NULL;
        }
    }
}

void lsf_driver_free(lsf_driver_type *driver) {
    free(driver->login_shell);
    free(driver->queue_name);
    free(driver->resource_request);
    free(driver->remote_lsf_server);
    free(driver->rsh_cmd);
    free(driver->bhist_cmd);
    free(driver->bkill_cmd);
    free(driver->bjobs_cmd);
    free(driver->bsub_cmd);
    free(driver->project_code);

    hash_free(driver->bjobs_cache);
    hash_free(driver->my_jobs);

    delete driver;
    driver = NULL;
}

void lsf_driver_free__(void *__driver) {
    auto driver = static_cast<lsf_driver_type *>(__driver);
    lsf_driver_free(driver);
}

static void lsf_driver_set_project_code(lsf_driver_type *driver,
                                        const char *project_code) {
    driver->project_code =
        util_realloc_string_copy(driver->project_code, project_code);
}

static void lsf_driver_set_queue(lsf_driver_type *driver, const char *queue) {
    driver->queue_name = util_realloc_string_copy(driver->queue_name, queue);
}

static void lsf_driver_set_login_shell(lsf_driver_type *driver,
                                       const char *login_shell) {
    driver->login_shell =
        util_realloc_string_copy(driver->login_shell, login_shell);
}

static void lsf_driver_set_rsh_cmd(lsf_driver_type *driver,
                                   const char *rsh_cmd) {
    driver->rsh_cmd = util_realloc_string_copy(driver->rsh_cmd, rsh_cmd);
}

static void lsf_driver_set_bsub_cmd(lsf_driver_type *driver,
                                    const char *bsub_cmd) {
    driver->bsub_cmd = util_realloc_string_copy(driver->bsub_cmd, bsub_cmd);
}

static void lsf_driver_set_bjobs_cmd(lsf_driver_type *driver,
                                     const char *bjobs_cmd) {
    driver->bjobs_cmd = util_realloc_string_copy(driver->bjobs_cmd, bjobs_cmd);
}

static void lsf_driver_set_bkill_cmd(lsf_driver_type *driver,
                                     const char *bkill_cmd) {
    driver->bkill_cmd = util_realloc_string_copy(driver->bkill_cmd, bkill_cmd);
}

static void lsf_driver_set_bhist_cmd(lsf_driver_type *driver,
                                     const char *bhist_cmd) {
    driver->bhist_cmd = util_realloc_string_copy(driver->bhist_cmd, bhist_cmd);
}

static void lsf_driver_set_remote_server(lsf_driver_type *driver,
                                         const char *remote_server) {
    if (remote_server != NULL) {
        driver->remote_lsf_server =
            util_realloc_string_copy(driver->remote_lsf_server, remote_server);
        unsetenv("BSUB_QUIET");
        {
            char *tmp_server = (char *)util_alloc_strupr_copy(remote_server);

            if (strcmp(tmp_server, LOCAL_LSF_SERVER) == 0)
                driver->submit_method = LSF_SUBMIT_LOCAL_SHELL;
            else if (
                strcmp(tmp_server, NULL_LSF_SERVER) ==
                0) // We trap the special string 'NULL' and call again with a true NULL pointer.
                lsf_driver_set_remote_server(driver, NULL);
            else
                driver->submit_method = LSF_SUBMIT_REMOTE_SHELL;

            free(tmp_server);
        }
    }
}

void lsf_driver_add_exclude_hosts(lsf_driver_type *driver,
                                  const char *excluded) {
    stringlist_type *host_list = stringlist_alloc_from_split(excluded, ", ");
    for (int i = 0; i < stringlist_get_size(host_list); i++) {
        const char *excluded = stringlist_iget(host_list, i);
        const auto &iter =
            std::find(driver->exclude_hosts.begin(),
                      driver->exclude_hosts.end(), std::string(excluded));
        if (iter == driver->exclude_hosts.end())
            driver->exclude_hosts.push_back(excluded);
    }
}

lsf_submit_method_enum
lsf_driver_get_submit_method(const lsf_driver_type *driver) {
    return driver->submit_method;
}

static bool lsf_driver_set_debug_output(lsf_driver_type *driver,
                                        const char *arg) {
    bool debug_output;
    bool OK = util_sscanf_bool(arg, &debug_output);
    if (OK)
        driver->debug_output = debug_output;

    return OK;
}

static bool lsf_driver_set_submit_sleep(lsf_driver_type *driver,
                                        const char *arg) {
    double submit_sleep;
    bool OK = util_sscanf_double(arg, &submit_sleep);
    if (OK)
        driver->submit_sleep = (int)(1000000 * submit_sleep);

    return OK;
}

void lsf_driver_set_bjobs_refresh_interval_option(lsf_driver_type *driver,
                                                  const char *option_value) {
    int refresh_interval;
    if (util_sscanf_int(option_value, &refresh_interval))
        lsf_driver_set_bjobs_refresh_interval(driver, refresh_interval);
}

bool lsf_driver_set_option(void *__driver, const char *option_key,
                           const void *value_) {
    const char *value = (const char *)value_;
    auto driver = static_cast<lsf_driver_type *>(__driver);
    bool has_option = true;
    {
        if (strcmp(LSF_RESOURCE, option_key) == 0)
            driver->resource_request =
                util_realloc_string_copy(driver->resource_request, value);
        else if (strcmp(LSF_SERVER, option_key) == 0)
            lsf_driver_set_remote_server(driver, value);
        else if (strcmp(LSF_QUEUE, option_key) == 0)
            lsf_driver_set_queue(driver, value);
        else if (strcmp(LSF_LOGIN_SHELL, option_key) == 0)
            lsf_driver_set_login_shell(driver, value);
        else if (strcmp(LSF_RSH_CMD, option_key) == 0)
            lsf_driver_set_rsh_cmd(driver, value);
        else if (strcmp(LSF_BSUB_CMD, option_key) == 0)
            lsf_driver_set_bsub_cmd(driver, value);
        else if (strcmp(LSF_BJOBS_CMD, option_key) == 0)
            lsf_driver_set_bjobs_cmd(driver, value);
        else if (strcmp(LSF_BKILL_CMD, option_key) == 0)
            lsf_driver_set_bkill_cmd(driver, value);
        else if (strcmp(LSF_BHIST_CMD, option_key) == 0)
            lsf_driver_set_bhist_cmd(driver, value);
        else if (strcmp(LSF_DEBUG_OUTPUT, option_key) == 0)
            lsf_driver_set_debug_output(driver, value);
        else if (strcmp(LSF_SUBMIT_SLEEP, option_key) == 0)
            lsf_driver_set_submit_sleep(driver, value);
        else if (strcmp(LSF_EXCLUDE_HOST, option_key) == 0)
            lsf_driver_add_exclude_hosts(driver, value);
        else if (strcmp(LSF_BJOBS_TIMEOUT, option_key) == 0)
            lsf_driver_set_bjobs_refresh_interval_option(driver, value);
        else if (strcmp(LSF_PROJECT_CODE, option_key) == 0)
            lsf_driver_set_project_code(driver, value);
        else
            has_option = false;
    }
    return has_option;
}

const void *lsf_driver_get_option(const void *__driver,
                                  const char *option_key) {
    const auto driver = static_cast<const lsf_driver_type *>(__driver);
    {
        if (strcmp(LSF_RESOURCE, option_key) == 0)
            return driver->resource_request;
        else if (strcmp(LSF_SERVER, option_key) == 0)
            return driver->remote_lsf_server;
        else if (strcmp(LSF_QUEUE, option_key) == 0)
            return driver->queue_name;
        else if (strcmp(LSF_LOGIN_SHELL, option_key) == 0)
            return driver->login_shell;
        else if (strcmp(LSF_RSH_CMD, option_key) == 0)
            return driver->rsh_cmd;
        else if (strcmp(LSF_BJOBS_CMD, option_key) == 0)
            return driver->bjobs_cmd;
        else if (strcmp(LSF_BSUB_CMD, option_key) == 0)
            return driver->bsub_cmd;
        else if (strcmp(LSF_BKILL_CMD, option_key) == 0)
            return driver->bkill_cmd;
        else if (strcmp(LSF_BHIST_CMD, option_key) == 0)
            return driver->bhist_cmd;
        else if (strcmp(LSF_PROJECT_CODE, option_key) == 0)
            /* Will be NULL if the project code has not been set. */
            return driver->project_code;
        else if (strcmp(LSF_BJOBS_TIMEOUT, option_key) == 0) {
            /* This will leak. */
            char *timeout_string = (char *)util_alloc_sprintf(
                "%d", driver->bjobs_refresh_interval);
            return timeout_string;
        } else {
            util_abort("%s: option_id:%s not recognized for LSF driver \n",
                       __func__, option_key);
            return NULL;
        }
    }
}

void lsf_driver_init_option_list(stringlist_type *option_list) {
    for (const auto &i : LSF_DRIVER_OPTIONS) {
        stringlist_append_copy(option_list, i.c_str());
    }
}

/**
   Observe that this driver IS not properly initialized when returning
   from this function, the option interface must be used to set the
   keys:
*/
void lsf_driver_set_bjobs_refresh_interval(lsf_driver_type *driver,
                                           int refresh_interval) {
    driver->bjobs_refresh_interval = refresh_interval;
}

static void lsf_driver_shell_init(lsf_driver_type *lsf_driver) {
    lsf_driver->last_bjobs_update = time(NULL);
    lsf_driver->bjobs_cache = hash_alloc();
    lsf_driver->my_jobs = hash_alloc();
    lsf_driver->bsub_cmd = NULL;
    lsf_driver->bjobs_cmd = NULL;
    lsf_driver->bkill_cmd = NULL;
    lsf_driver->bhist_cmd = NULL;

    pthread_mutex_init(&lsf_driver->bjobs_mutex, NULL);
}

/**
  If the lsb library is compiled in and the runtime loading of the lsb libraries
  has succeeded we default to submitting through internal library calls,
  otherwise we will submit using shell commands on the local workstation.
*/
static void lsf_driver_init_submit_method(lsf_driver_type *driver) {
    driver->submit_method = LSF_SUBMIT_LOCAL_SHELL;
}

bool lsf_driver_has_project_code(const lsf_driver_type *driver) {
    if (driver->project_code)
        return true;
    else
        return false;
}

void *lsf_driver_alloc() {
    lsf_driver_type *lsf_driver = new lsf_driver_type();

    lsf_driver->submit_method = LSF_SUBMIT_INVALID;
    lsf_driver->login_shell = NULL;
    lsf_driver->queue_name = NULL;
    lsf_driver->remote_lsf_server = NULL;
    lsf_driver->rsh_cmd = NULL;
    lsf_driver->resource_request = NULL;
    lsf_driver->project_code = NULL;
    lsf_driver->error_count = 0;
    lsf_driver->max_error_count = MAX_ERROR_COUNT;
    lsf_driver->submit_error_sleep = SUBMIT_ERROR_SLEEP * 1000000;
    pthread_mutex_init(&lsf_driver->submit_lock, NULL);

    lsf_driver_shell_init(lsf_driver);
    lsf_driver_init_submit_method(lsf_driver);

    lsf_driver_set_option(lsf_driver, LSF_SERVER, NULL);
    lsf_driver_set_option(lsf_driver, LSF_RSH_CMD, DEFAULT_RSH_CMD);
    lsf_driver_set_option(lsf_driver, LSF_BSUB_CMD, DEFAULT_BSUB_CMD);
    lsf_driver_set_option(lsf_driver, LSF_BJOBS_CMD, DEFAULT_BJOBS_CMD);
    lsf_driver_set_option(lsf_driver, LSF_BKILL_CMD, DEFAULT_BKILL_CMD);
    lsf_driver_set_option(lsf_driver, LSF_BHIST_CMD, DEFAULT_BHIST_CMD);
    lsf_driver_set_option(lsf_driver, LSF_DEBUG_OUTPUT, "FALSE");
    lsf_driver_set_option(lsf_driver, LSF_SUBMIT_SLEEP, DEFAULT_SUBMIT_SLEEP);
    lsf_driver_set_option(lsf_driver, LSF_BJOBS_TIMEOUT, BJOBS_REFRESH_TIME);
    return lsf_driver;
}
