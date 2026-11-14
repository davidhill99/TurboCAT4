cask "turbocat" do
  arch arm: "AppleSilicon", intel: "Intel"

  version "4.0.0-beta.1"
  sha256 arm:   "FILL-IN-AFTER-RELEASE",
         intel: "FILL-IN-AFTER-RELEASE"

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
