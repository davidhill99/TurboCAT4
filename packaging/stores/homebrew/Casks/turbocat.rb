cask "turbocat" do
  arch arm: "AppleSilicon", intel: "57f86146770294c4b7c1b5ce0752e3537e9bf890db5d238d6877d0dd578ced3d"

  version "4.0.0-beta.2"
  sha256 arm:   "f7fe33a884d5251beff15f2131a6c726434295bfe737cf0359a297704f9964f3",
         intel: "57f86146770294c4b7c1b5ce0752e3537e9bf890db5d238d6877d0dd578ced3d"

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
