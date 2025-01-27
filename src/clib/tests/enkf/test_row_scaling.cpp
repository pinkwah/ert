#include "catch2/catch.hpp"
#include <Eigen/Dense>
#include <chrono>
#include <iostream>
#include <random>
#include <stdexcept>
#include <stdlib.h>
#include <vector>

#include <ert/enkf/row_scaling.hpp>

#define assert_throw(expr, exception_type)                                     \
    {                                                                          \
        bool throw_ok = false;                                                 \
        try {                                                                  \
            expr;                                                              \
        } catch (std::exception & e) {                                         \
            if (dynamic_cast<exception_type *>(&e))                            \
                throw_ok = true;                                               \
        }                                                                      \
        REQUIRE(throw_ok);                                                     \
    }

TEST_CASE("row_scaling_create", "[row_scaling]") {
    RowScaling row_scaling;
    REQUIRE(row_scaling.size() == 0);

    assert_throw(row_scaling[-1], std::out_of_range);
    assert_throw(row_scaling[1000], std::out_of_range);

    assert_throw(row_scaling.assign(-1, 0), std::out_of_range);
    assert_throw(row_scaling.assign(0, -1), std::invalid_argument);
    assert_throw(row_scaling.assign(0, 2), std::invalid_argument);

    row_scaling.assign(9, 0.25);
    CHECK(row_scaling[9] == Approx(0.25).epsilon(1e-12));
}

void row_scaling_multiply2(const RowScaling &row_scaling, Eigen::MatrixXd &A,
                           const Eigen::MatrixXd &X0) {
    Eigen::MatrixXd X = Eigen::MatrixXd::Zero(X0.rows(), X0.cols());
    for (int row = 0; row < row_scaling.size(); row++) {
        double alpha = row_scaling[row];
        scaleX(X, X0, alpha);

        std::vector<double> row_data(A.cols());
        for (int j = 0; j < A.cols(); j++) {
            double sum = 0;
            for (int i = 0; i < A.cols(); i++)
                sum += A(row, i) * X(i, j);

            row_data[j] = sum;
        }
        if (row < 0 || row >= A.rows())
            throw std::invalid_argument("Invalid row index");

        for (int j = 0; j < A.cols(); j++)
            A(row, j) = row_data.data()[j];
    }
}

void test_multiply(const RowScaling &row_scaling, const Eigen::MatrixXd &A0,
                   const Eigen::MatrixXd &X0) {
    Eigen::MatrixXd A1 = A0;
    Eigen::MatrixXd A2 = A0;

    row_scaling.multiply(A1, X0);
    row_scaling_multiply2(row_scaling, A2, X0);
    REQUIRE(A1 == A2);
}

TEST_CASE("row_scaling_multiply", "[row_scaling]") {
    const int data_size = 200;
    const int ens_size = 100;
    Eigen::MatrixXd A0 = Eigen::MatrixXd::Random(data_size, ens_size);
    Eigen::MatrixXd X0 = Eigen::MatrixXd::Zero(ens_size, ens_size);
    const auto random_double = [] {
        static std::default_random_engine engine{std::random_device{}()};
        return std::uniform_real_distribution<double>{}(engine);
    };

    const int project_iens = 4;
    for (int col = 0; col < ens_size; col++)
        X0(project_iens, col) = 1.0;

    // alpha == 1: Full update, should project out realizations project_iens
    {
        RowScaling row_scaling;
        Eigen::MatrixXd A = A0;
        for (int row = 0; row < data_size; row++)
            row_scaling.assign(row, 1);
        row_scaling.multiply(A, X0);

        for (int row = 0; row < data_size; row++)
            for (int col = 0; col < ens_size; col++)
                CHECK(A(row, col) ==
                      Approx(A0(row, project_iens)).epsilon(1e-12));

        test_multiply(row_scaling, A0, X0);
    }

    // alpha == 0: No update - should have A == A0
    {
        RowScaling row_scaling;
        Eigen::MatrixXd A = A0;
        std::vector<float> row_data(data_size);
        for (int row = 0; row < data_size; row++)
            row_data[row] = 0;

        row_scaling.assign_vector(row_data.data(), row_data.size());
        row_scaling.multiply(A, X0);

        for (int row = 0; row < data_size; row++)
            for (int col = 0; col < ens_size; col++)
                CHECK(A(row, col) == Approx(A0(row, col)).epsilon(1e-12));

        test_multiply(row_scaling, A0, X0);
    }

    // General alpha
    {
        RowScaling row_scaling;
        Eigen::MatrixXd A = A0;
        std::vector<double> row_data(data_size);

        row_scaling.assign(2 * data_size, 1.0);
        REQUIRE(row_scaling.size() == 2 * data_size + 1);

        for (int row = 0; row < data_size; row++)
            row_data[row] = random_double();

        row_scaling.assign_vector(row_data.data(), row_data.size());
        REQUIRE(row_scaling.size() == data_size);

        row_scaling.multiply(A, X0);
        for (int row = 0; row < data_size; row++) {
            double alpha = row_scaling[row];
            for (int col = 0; col < ens_size; col++) {
                double expected =
                    alpha * A0(row, project_iens) + (1 - alpha) * A0(row, col);
                CHECK(A(row, col) == Approx(expected).epsilon(1e-12));
            }
        }

        test_multiply(row_scaling, A0, X0);
    }
}
