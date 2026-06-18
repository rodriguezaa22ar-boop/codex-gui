{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  packages = with pkgs; [
    git
    gobject-introspection
    gtk4
    python3
    python3Packages.pygobject3
    rsync
    tailscale
  ];

  shellHook = ''
    export GDK_BACKEND=''${GDK_BACKEND:-wayland,x11}
    export PYTHONPATH="$PWD:''${PYTHONPATH:-}"
    echo "Codex Control dev shell: python3, GTK 4, git, rsync, tailscale"
  '';
}
