{
  description = "Festin — Babette's kitchen app";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAll = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in {
      devShells = forAll (pkgs: {
        default = pkgs.mkShell {
          packages = [
            pkgs.nodejs_22
            (pkgs.python3.withPackages (ps: [ ps.pytest ps.pillow ]))
            pkgs.sqlite
            pkgs.liberation_ttf
            pkgs.ffmpeg
          ];
          shellHook = ''
            export FESTIN_FONT_DIR="${pkgs.liberation_ttf}/share/fonts/truetype"
          '';
        };
      });
    };
}
