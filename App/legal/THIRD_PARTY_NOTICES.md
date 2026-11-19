# Credits and third-party licenses

SC Co-Pilot is built on these open-source projects. Thank you to everyone who makes them.

The installer bundles the components marked **bundled**. Components marked **downloaded** are fetched the first time you use the feature. Components marked **source only** are used only when you run SC Co-Pilot from source with `Install.bat`.

| Component | Used for | License | How it ships |
|---|---|---|---|
| [Python](https://www.python.org/) | Runs the app | PSF License | bundled |
| [Tcl/Tk](https://www.tcl.tk/) | The window and controls | Tcl/Tk License (BSD-style) | bundled |
| [NumPy](https://numpy.org/) | Audio processing | BSD-3-Clause | bundled |
| [python-sounddevice](https://github.com/spatialaudio/python-sounddevice) | Microphone and speaker | MIT | bundled |
| [PortAudio](https://www.portaudio.com/) | Audio input/output (via sounddevice) | MIT-style | bundled |
| [python-soundfile](https://github.com/bastibe/python-soundfile) | Decoding voice audio | BSD-3-Clause | bundled |
| [libsndfile](https://github.com/libsndfile/libsndfile) | Audio decoding (via soundfile) | LGPL-2.1-or-later | bundled as a separate, replaceable DLL |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Speech recognition | MIT | bundled |
| [CTranslate2](https://github.com/OpenNMT/CTranslate2) | Runs the speech model | MIT | bundled |
| [PyAV](https://github.com/PyAV-Org/PyAV) | Audio decoding (via faster-whisper) | BSD-3-Clause | bundled |
| [FFmpeg](https://ffmpeg.org/) | Audio libraries (via PyAV) | LGPL-2.1-or-later | bundled as separate, replaceable DLLs |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) | Voice-activity detection model | MIT | bundled |
| [Tokenizers](https://github.com/huggingface/tokenizers), [huggingface_hub](https://github.com/huggingface/huggingface_hub) | Loading the speech model | Apache-2.0 | bundled |
| [Whisper models](https://github.com/openai/whisper) (Systran faster-whisper conversions) | Speech recognition | MIT | downloaded |
| [edge-tts](https://github.com/rany2/edge-tts) | Microsoft online voices | LGPL-3.0 | bundled as plain, replaceable Python files |
| [python-zstandard](https://github.com/indygreg/python-zstandard) | Reading the game's default keybinds | BSD-3-Clause | bundled |
| [Pillow](https://github.com/python-pillow/Pillow) | Shrinking screenshots for screen checks | MIT-CMU | bundled |
| [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) | Kokoro offline voices | MIT | source only |
| [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) | Kokoro voice model | Apache-2.0 | downloaded (source only) |
| [phonemizer](https://github.com/bootphon/phonemizer), [espeak-ng](https://github.com/espeak-ng/espeak-ng) | Kokoro pronunciation | GPL-3.0 | source only |

The full license text for each component is in its repository at the link above. For the LGPL components, you can replace the bundled library files with your own builds. The source code is available at those links.

## Data and services

- **Price, location, ship and item data** come from the community-run [UEX Corp](https://uexcorp.space/) API. UEX is not affiliated with Cloud Imperium Games.
- **AI answers** come from Anthropic's Claude API, using your own key or the Co-Pilot subscription.
- **Microsoft voices** use Microsoft's online text-to-speech service through edge-tts.

## Star Citizen

SC Co-Pilot is an unofficial fan-made tool. It is not affiliated with, endorsed by or sponsored by Cloud Imperium Games or Roberts Space Industries. Star Citizen®, Squadron 42®, Roberts Space Industries® and Cloud Imperium® are trademarks of Cloud Imperium Rights LLC.
