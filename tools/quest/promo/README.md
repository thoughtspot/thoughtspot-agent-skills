# AgentQL Quest: promo

An advert for the game, in the game's own amber-CRT style: the Wizard (the AI) writes the
scroll, the dwarves of the Forge (ThoughtSpot) compile it, a dragon made of SQL rises from the
fire, and the player names who wrote each line.

| File | Use |
|---|---|
| [`agentql-quest-poster.png`](agentql-quest-poster.png) | Still poster (960x600). Used on the Pages home page and in docs |
| [`agentql-quest.gif`](agentql-quest.gif) | 21-second looping animation (960x600, under 1 MB), for Slack |
| [`make_ad.py`](make_ad.py) | Draws both, and the frames for the video. All art and the font are original |
| [`encode_mp4.swift`](encode_mp4.swift) | Encodes the frames to an H.264 MP4 with macOS's own AVFoundation (no ffmpeg) |

The MP4 (1920x1200, 30 fps, about 4 MB) is not committed: git keeps every version of a binary
forever, and it is two commands away.

```bash
python3 tools/quest/promo/make_ad.py /tmp/aqq --video-frames
swift tools/quest/promo/encode_mp4.swift /tmp/aqq/video-frames/manifest.txt /tmp/aqq/agentql-quest.mp4 30
```

Regenerate after a change to the game's story or wording, and copy the poster and GIF back
here. The advert says "link in the post" rather than showing the address, because Pages paths
are case-sensitive and the pixel font is capitals only.
