"""The Troubleshooting Guide: plain answers for when something will not open,
play, sound or show. Each topic may carry actions the window can do for you.

Actions: "fix_passthrough", "show_on_tv", "open_bios", "download:<tool>",
"install:<tool>", "page:programs", "page:settings".
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Topic:
    id: str
    title: str
    section: str
    words: str                      # extra search words
    body: str                       # simple HTML
    actions: list[tuple[str, str]] = field(default_factory=list)


T = Topic
TOPICS: list[Topic] = [
    # --- films and shows ----------------------------------------------------------
    T("no-sound-tv", "No sound on the TV", "Films and shows",
      "silent mute audio hdmi dolby eac3 ac3 truehd dts passthrough speakers",
      """<p>The picture plays but the TV is silent. The usual cause: the film's sound is
      Dolby or DTS, the HDMI connection says the TV can decode it, so the player sends it
      undecoded, and the TV plays nothing.</p>
      <ol><li>Press <b>Send plain sound to the TV</b> below. The computer then decodes the
      sound itself and the TV gets ordinary audio.</li>
      <li>Close the film and open it again from Bramble (a player that is already
      playing keeps the old setting).</li>
      <li>Still silent: check the TV is not muted, and that the computer's sound output
      is the TV (on Linux, the volume icon or <code>wpctl status</code>; on Windows, the
      speaker icon in the taskbar).</li></ol>""",
      [("Send plain sound to the TV", "fix_passthrough")]),
    T("tv-blank", "The TV shows nothing", "Films and shows",
      "hdmi display monitor screen black no signal projector mirror",
      """<p>The cable is in but the TV says <i>no signal</i>, or stays black.</p>
      <ol><li>Set the TV to the right input (HDMI 1, HDMI 2...) with its remote.</li>
      <li>Press <b>Show the picture on the TV</b> below. Bramble turns the TV on from the
      computer's side and shows the same picture as the laptop.</li>
      <li>On Windows press <b>Windows key + P</b> and choose <b>Duplicate</b>.</li>
      <li>Try the other end of the cable, or another HDMI port on the TV.</li></ol>""",
      [("Show the picture on the TV", "show_on_tv")]),
    T("subtitles", "Subtitles", "Films and shows",
      "captions srt subs language forced sdh english",
      """<p>Bramble turns on the film's full English subtitles when it opens it (change this
      in SETTINGS). Inside VLC press <b>V</b> to step through the subtitle tracks, or
      right-click the picture and choose <b>Subtitle &gt; Sub Track</b>. In mpv press
      <b>J</b>.</p>
      <p><b>Forced</b> tracks only show lines spoken in another language. <b>SDH</b> adds
      sound descriptions such as [door creaks].</p>
      <p><b>No subtitles in the file:</b> download an <code>.srt</code> for the same release
      (sites such as OpenSubtitles or Subdl) and save it beside the film with the same
      name, e.g. <code>Hokum.2026.1080p.en.srt</code>. Bramble finds it there.</p>
      <p><b>Subtitles early or late:</b> in VLC press <b>G</b> or <b>H</b> to move them by
      50 ms at a time; in mpv <b>Z</b> and <b>X</b>.</p>"""),
    T("stutter", "The film stutters or freezes", "Films and shows",
      "lag choppy slow 4k hevc x265 10bit av1 dropped frames",
      """<p>Very sharp films (4K, x265/HEVC, AV1, 10-bit) take a lot of work to decode, and an
      older computer can fall behind.</p>
      <ol><li>Open it with <b>mpv</b> instead (the <b>Open with</b> menu). It is often
      smoother.</li><li>Close games and browsers running in the background.</li>
      <li>Playing from the drive: a USB 2 port (black inside) is slow; use a blue or USB-C
      port.</li><li>Use a 1080p copy of the film.</li></ol>"""),
    T("hdr", "Colours look washed out", "Films and shows",
      "hdr dolby vision grey pale dull colours",
      """<p>HDR films shown on an ordinary screen can look grey. VLC and mpv convert HDR for
      normal screens; if one looks wrong, try the other through <b>Open with</b>. A
      non-HDR (SDR) copy of the film always looks right.</p>"""),
    T("still-downloading", "It is still downloading", "Films and shows",
      "partial incomplete torrent qbittorrent part crdownload",
      """<p>Bramble marks a file <i>still downloading</i> when it changed in the last minute
      and a half, or ends in <code>.part</code>, <code>.!qB</code> or
      <code>.crdownload</code>. Playing it early usually works for the start, then stops
      or skips. Wait for the download to finish.</p>
      <p>Torrents: moving a file out of the download folder while it is still seeding makes
      the torrent program lose it. Use <b>Copy</b> when filing it, or remove the torrent
      first.</p>"""),
    T("damaged-file", "The file will not open at all", "Films and shows",
      "corrupt broken damaged incomplete error",
      """<p>If no player can read the file, it is probably incomplete or damaged.</p>
      <ol><li>Check its size against what it should be.</li><li>If it came from a
      torrent, run a recheck in the torrent program, which re-downloads broken pieces.</li>
      <li>Download it again from a different source.</li></ol>"""),
    T("no-player", "No video player on this PC", "Films and shows",
      "vlc mpv missing install player",
      """<p>Bramble carries VLC (Windows) and mpv (Linux and Windows) on the drive and uses
      them automatically. If neither is here, install VLC: on Linux it asks for this
      PC's password, on Windows it uses the Windows package manager.</p>""",
      [("Install VLC on this PC", "install:vlc"), ("Download mpv for Bramble", "download:mpv")]),

    # --- games -------------------------------------------------------------------
    T("bios", "A game asks for a BIOS", "Games",
      "bios playstation ps1 scph firmware system files",
      """<p>Some consoles (PlayStation especially) need a BIOS file copied from a console
      you own. Bramble cannot supply it.</p>
      <p>Put it in <b>MARROW / Video Games / BIOS</b>. Bramble tells RetroArch to look
      there, on any PC. For PlayStation one of <code>scph5501.bin</code>,
      <code>scph5500.bin</code> or <code>scph5502.bin</code> is enough.</p>""",
      [("Open the BIOS folder", "open_bios")]),
    T("rom-folders", "Where retro games go", "Games",
      "roms folders console system snes n64 nes gba psx",
      """<p>Put each console's games in its own folder under <b>Video Games</b>:
      <code>NES</code>, <code>SNES</code>, <code>Nintendo 64</code>, <code>Game Boy</code>,
      <code>Game Boy Color</code>, <code>Game Boy Advance</code>, <code>Nintendo DS</code>,
      <code>Genesis</code>, <code>Master System</code>, <code>Game Gear</code>,
      <code>PlayStation</code>, <code>PSP</code>, <code>PC Engine</code>,
      <code>Atari 2600</code>, <code>Arcade</code>.</p>
      <p>Zipped games work inside these folders. Games whose file type is unique (like
      <code>.sfc</code> or <code>.gba</code>) are recognised anywhere.</p>"""),
    T("retroarch-keys", "Playing retro games", "Games",
      "retroarch controls menu quit save state controller gamepad keyboard",
      """<ul><li><b>F1</b> opens RetroArch's menu (controls, save states, quit).</li>
      <li><b>Esc</b> twice quits.</li><li><b>F2</b> saves a state, <b>F4</b> loads it.</li>
      <li>Controllers are set up automatically for most Xbox and PlayStation pads. If
      buttons are wrong: F1 &gt; Settings &gt; Input &gt; Port 1 Controls.</li>
      <li>Game saves are kept beside RetroArch on each PC.</li></ul>"""),
    T("windows-games-linux", "Windows games on Linux", "Games",
      "proton wine exe dxvk anti-cheat",
      """<p>On Linux, Bramble runs Windows games through <b>GE-Proton</b> (the same tool
      Steam uses), falling back to Wine. The first start on a PC takes a minute while it
      sets up.</p>
      <ul><li>Online games with anti-cheat (Fortnite, Valorant...) usually refuse to
      run.</li><li>If a game opens a launcher first, that is the game's own launcher.</li>
      <li>If it fails, try <b>Open with &gt; Wine</b>, or check the game on
      <a href="https://www.protondb.com">ProtonDB</a> for tips.</li>
      <li>Missing DLL errors: many games ship a <code>_Redist</code> or <code>_CommonRedist</code>
      folder; run the installers in it once through <b>Open with</b>.</li></ul>""",
      [("Download GE-Proton for Bramble", "download:proton"), ("Install Wine on this PC", "install:wine")]),
    T("game-wont-start", "A PC game will not start", "Games",
      "exe crash closes immediately missing dll vcruntime directx",
      """<ol><li>Some games need Microsoft's runtime libraries. Look in the game's folder for
      <code>_Redist</code>, <code>_CommonRedist</code>, <code>vcredist</code> or
      <code>DirectX</code> and run what is inside once.</li>
      <li>Bramble picks the game's main <code>.exe</code> automatically. If it picked the wrong
      one, use <b>Open with &gt; Choose the program file</b>.</li>
      <li>On Windows, if it says <i>Windows protected your PC</i>, see
      <b>Windows blocks a program</b>.</li></ol>"""),
    T("wrong-os", "Made for a different system", "Games",
      "linux windows deb exe appimage wrong platform",
      """<p><code>.exe</code> and <code>.msi</code> files are for Windows (Linux runs them
      through Proton/Wine). <code>.deb</code>, <code>.AppImage</code> and <code>.sh</code>
      are for Linux and cannot run on Windows. Look for the other version of the program
      or game.</p>"""),

    # --- the drive -----------------------------------------------------------------
    T("linux-drive-exec", "Linux will not run things from the drive", "The drive",
      "permission denied exfat exec noexec chmod",
      """<p>The drive uses exFAT so both Windows and Linux can read it, but Linux cannot mark
      files on exFAT as runnable. Bramble works around this itself: carried programs are
      copied to this PC the first time (a short wait), and Linux games run through the
      system loader. Nothing for you to do unless a game insists; then copy its folder to
      the PC and open it from there.</p>"""),
    T("smartscreen", "Windows blocks a program", "The drive",
      "smartscreen windows protected your pc unknown publisher defender antivirus",
      """<p><i>Windows protected your PC</i> appears for programs Windows has not seen
      before. If you trust it, click <b>More info</b> then <b>Run anyway</b>. If an
      antivirus removes a file from the drive, restore it from the antivirus's
      quarantine and mark it as allowed.</p>"""),
    T("drive-missing", "The drive does not show up", "The drive",
      "usb not detected not showing letter mount",
      """<ol><li>Unplug it, wait five seconds, plug it into a different port.</li>
      <li>Windows: open File Explorer; it appears as <b>hawthorn</b>. If not, open
      <b>Disk Management</b> and give it a drive letter.</li>
      <li>Linux: open the file manager and click it in the side bar to mount it.</li>
      <li>Always use <b>Eject</b> before unplugging, or files being copied can be
      damaged.</li></ol>"""),
    T("password", "It asks for a password", "The drive",
      "pkexec sudo password admin uac install",
      """<p>Installing a program on a PC (VLC, Wine) needs that PC's owner to agree: Linux
      asks for the PC's password, Windows shows a <b>Yes/No</b> prompt. Bramble never asks
      for or stores a password itself. Using the copies carried on the drive needs no
      password at all.</p>"""),
    T("offline", "No internet", "The drive",
      "offline network download failed",
      """<p>Everything Bramble carries works offline. Only looking for newer versions or
      downloading a missing program needs the internet; Bramble tries several sources
      before giving up.</p>"""),
    T("nothing-opens", "Nothing opens it", "The drive",
      "fails error not working nothing happens",
      """<ol><li>Read the list Bramble shows: it says which programs were tried and how each
      failed.</li><li>Try <b>Open with</b> and pick a different program.</li>
      <li>Press <b>Look for a newer</b> version of the program that failed; a newer one may
      read the file.</li><li>Check the file is complete (see <b>The file will not open at
      all</b>).</li><li>The PROGRAMS page shows every program Bramble can use on this PC
      and on the drive.</li></ol>""",
      [("Open PROGRAMS", "page:programs")]),
]

BY_ID = {t.id: t for t in TOPICS}
SECTIONS = list(dict.fromkeys(t.section for t in TOPICS))


def search(text: str) -> list[Topic]:
    words = text.lower().split()
    if not words:
        return TOPICS
    out = []
    for t in TOPICS:
        hay = f"{t.title} {t.words} {t.body}".lower()
        if all(w in hay for w in words):
            out.append(t)
    return out
