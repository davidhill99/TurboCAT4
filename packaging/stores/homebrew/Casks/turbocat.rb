cask "turbocat" do
  arch arm: "AppleSilicon", intel: "Intel"

  version "4.0.0-beta.1"
  sha256 arm:   "3650762e59b3d9fa5736906f4116228c026d277ce2a367ad824650790c188f3d",
         intel: "bd87ac644f6682c8d78ae20d939e369347284b8f377e299aa86a022c0616893a"

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
