{ pkgs, lib, config, inputs, ... }:

let
  python = pkgs.python312;
in {
  languages.python = {
    enable = true;
    package = python;
    uv.enable = true;
    uv.sync.enable = true;
    uv.sync.allExtras = true;
    venv.enable = true;
  };

  env = {
    PYTHONPATH = "${python.pkgs.pyqt6}/${python.sitePackages}";
    QT_PLUGIN_PATH = "${config.devenv.profile}/${pkgs.qt6.qtbase.qtPluginPrefix}";
    XDG_CONFIG_DIRS = "${config.devenv.state}";
  };

  packages = with pkgs; ([
    libz
    qt6.qtbase
    qt6.qtsvg

  ] ++ (lib.optionals pkgs.stdenv.isLinux [
    qt6.qtwayland

    # Theming on Linux
    qadwaitadecorations-qt6
    kdePackages.plasma-integration
  ]));
}
