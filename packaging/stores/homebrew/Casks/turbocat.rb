cask "turbocat" do
  arch arm: "AppleSilicon", intel: "Intel"

  version "4.0.0-beta.1"
  sha256 arm:   "00b87c5c257648afc6fcfa492ad00445bc2ce9c070be1a36756f6ca4c8d910bf",
         intel: "4b742330a3469be552ec03f48c7b9928da17e3f36225cc1381482911799b9214"

  url "https://github.com/davidhill99/TurboCAT4/releases/download/v#{version}/TurboCAT-#{version}-macOS-#{arch}.dmg"
  name "TurboCAT 4"
  desc "Catalogue, search and repair Amiga disk images"
  homepage "https://github.com/davidhill99/TurboCAT4"

  app "TurboCAT.app"

  zap trash: [
    "~/Library/Application Support/TurboCAT",
    "~/Library/Caches/TurboCAT",
  ]

  caveats <<~EOS
    TurboCAT isn't signed by Apple yet: the first time, right-click TurboCAT and choose Open.
  EOS
end
