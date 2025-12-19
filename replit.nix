{ pkgs }: {
  deps = [
    pkgs.python311Full
    pkgs.python311Packages.pip
    pkgs.ffmpeg-full
    pkgs.libopus
    pkgs.libffi
    pkgs.gcc
  ];
}
