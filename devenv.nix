{
  pkgs,
  lib,
  config,
  inputs,
  ...
}:
let
  pkgs-unstable = import inputs.nixpkgs-unstable { system = pkgs.stdenv.system; };
in
{
  packages = [
    pkgs.gitFull
    pkgs.gnumake
    pkgs.libmysqlclient
    pkgs-unstable.opencode
    pkgs.nixd
    pkgs.djlint
  ];

  languages.nix.enable = true;

  languages.python = {
    enable = true;
    venv.enable = true;
    uv = {
      enable = true;
      sync.enable = true;
    };
  };

  git-hooks.hooks = {
    black.enable = true;
    flake8.enable = true;
    isort.enable = true;
    pyright.enable = false;
    python-debug-statements.enable = true;
    check-shebang-scripts-are-executable.enable = true;
    check-symlinks.enable = true;
    check-yaml.enable = true;
    check-merge-conflicts.enable = true;
    check-json.enable = true;
    check-executables-have-shebangs.enable = true;
    check-added-large-files.enable = true;
    check-case-conflicts.enable = true;
    markdownlint.enable = true;
    nixfmt.enable = true;
    prettier.enable = true;
    trufflehog.enable = true;
  };

  devcontainer.enable = true;
}
