# WoTH Tools

A collection of tools for unpacking and rebuilding files from **Witch on the Holy Night (Mahoyo) Remastered** (Steam), developed for the **Moonlit Translation** fan translation project.

---
## Result Comparison
| In-Game (English) | Decoded MZP |
|---|---|
| ![ingame](https://i.imgur.com/1nPcH5G.png) | ![decoded](https://i.imgur.com/FE3c6MK.png) |

---
## File Structure
This game uses four proprietary file formats, each handling a different type of asset. This repo provides a Python tool for each format.

| File | Format | Function |
|---|---|---|
| `hfa_tool.py` | `.hfa` — HuneX File Archive | Unpack and repack the game's main archive |
| `ctd_tool.py` | `.ctd` — Script text | Decompress and compress dialogue script files |
| `cbg_tool.py` | `.cbg` — Background / UI | Decode and encode background and UI images |
| `mzp_tool.py` | `.mzp` — Sprite / CG | Decode and encode sprite and CG images |

Each format uses its own compression algorithm. `.ctd` uses LenZuCompressor (LZ77 + Huffman, LSB-first). `.cbg` uses Huffman with zero-alternate and delta filtering. `.mzp` uses an MZX tile system combining RLE, LZ, and Huffman. `.hfa` uses no compression at all and functions purely as an archive container.

---
## Requirements
```bash
pip install numpy Pillow
```
Python 3.10 or newer.

---
## How to Use

### HFA — Main Archive
```bash
python hfa_tool.py list    data00300.hfa          # Show archive contents list
python hfa_tool.py unpack  data00300.hfa          # Extract all contents
python hfa_tool.py repack  output_folder/  data00300_new.hfa  # Repack
```

### CTD — Dialogue Script
```bash
python ctd_tool.py info         script_text_en.ctd        # File header info
python ctd_tool.py decompress   script_text_en.ctd        # Extract to .txt
python ctd_tool.py compress     output.txt  script_text_en.ctd  # Compress back
```

### CBG — Background and UI
```bash
python cbg_tool.py info    caution_en.cbg    # File info
python cbg_tool.py decode  caution_en.cbg    # Decode to .png
python cbg_tool.py encode  output.png  caution_en.cbg  # Encode back
```

### MZP — Sprite and CG
```bash
python mzp_tool.py info    img0499.mzp       # File info
python mzp_tool.py decode  img0499.mzp       # Decode to .png
python mzp_tool.py encode  output.png  img0499.mzp   # Encode back
```

The `Title image/` folder contains sample files that can be used to try out this tool. For the `encode` command, the original `.mzp` file **must be included** as a reference for tile parameters — without it, the encoding process cannot run.

---
## Credits
File formats were analyzed based on references from [loicfrance/mahoyo_tools](https://github.com/loicfrance/mahoyo_tools). The game and all its assets belong to **TYPE-MOON** / **HuneX**.

---
## Disclaimer
This tool is created for educational and fan translation purposes. Use it in accordance with the copyright rules and Terms of Service of the original game.
