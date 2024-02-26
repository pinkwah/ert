
Welcome to the ERT Documentation!
=================================

ERT (Ensemble based Reservoir Tool) is a free and open-source tool for automating complex workflows,
such as uncertainty quantification and data assimilation.
It is heavily used in the petroleum industry for reservoir management and production optimization,
but ERT is a general tool and is used in other domains, such as wind-farm management and Carbon Capture and Storage (CCS).

If you're new to ERT:

1. Begin by ensuring you've correctly installed it.
   Check out the :doc:`manual/setup` guide for assistance.
2. Follow the :doc:`manual/configuration/poly_new/guide` to learn how to use ERT for parameter estimation.

To understand the theoretical foundations of ensemble-based methods, head over to :doc:`manual/ensemble_based_methods`.

.. toctree::
   :hidden:

   self

.. toctree::
   :hidden:
   :caption: User Manual

   manual/getting_started/index

   manual/setup
   manual/configuration/poly_new/guide
   manual/howto/esmda_restart
   manual/howto/adaptive_localization.ipynb
   manual/webviz-ert/webviz-ert
   manual/concepts
   manual/forward_model

   manual/ensemble_based_methods

   manual/running_ert
   manual/configuration/index
   manual/workflows/index
   manual/release_notes/index

.. toctree::
   :hidden:
   :caption: Python API

   api/plugin_system

.. toctree::
   :hidden:
   :caption: Developer Documentation

   developer/roadmap
   developer/dev-strategy
   developer/storage_server
   developer/qt

.. toctree::
   :hidden:
   :caption: About

   PyPI releases <https://pypi.org/project/ert/>
   Code in GitHub <https://github.com/equinor/ert>
   Issue tracker <https://github.com/equinor/ert/issues>

.. Indices and tables
   ==================

   * :ref:`genindex`
   * :ref:`modindex`
   * :ref:`search`
