# pass_generator Q3 (v1.2.0)

> **Q3** is a personal OPSEC tool for generating random passwords for work and OSINT accounts. It runs locally and offline, draws randomness only from the operating system's cryptographic generator through Python's `secrets` module, shows the exact entropy of every password, and copies the result to the clipboard with one key. It does not store, log, or transmit generated passwords.

<!-- screenshot of the main menu goes here -->

## Features

- **No third-party dependencies:** uses the Python standard library; no `pip install` is required.
- **Cryptographic randomness only:** every character comes from `secrets`, i.e. the OS CSPRNG (`BCryptGenRandom` on Windows). No custom random number generator and no `random` module.
- **Uniform character selection:** characters are picked with `secrets.choice`, without `byte % N` modulo bias.
- **Correct required classes:** "at least one character of each enabled class" is enforced by rejection sampling, so the result stays uniform over all valid passwords.
- **Exact entropy:** calculated from the real alphabet after all exclusions and constraints, not from fixed values.
- **Flexible character sets:** lowercase, uppercase, digits and symbols can be toggled individually; ambiguous characters (`0 O o 1 l I |`) and any custom characters can be excluded. Symbols can be switched off with one key for sites that reject them.
- **Quick lengths:** 10, 12, 16, 20, 24 and 32 on a single key, or any custom length from 8 to 64.
- **One-key copy:** copies through the Win32 API and marks the content as excluded from Windows clipboard history and cloud clipboard sync.
- **Clipboard auto-clear:** 30 seconds after a copy the clipboard is emptied, but only if it still holds that copy.
- **Hidden mode:** masks the password on screen for screen sharing and recording; copy still works.
- **No traces by design:** no database, no history, no log files, no settings files, no network calls. Settings live only for the current run.
- **Keyboard-layout aware:** single-key controls work in English, Russian and Ukrainian layouts.

## Requirements

- Windows 10 (the included `run.bat` launcher and the clipboard are Windows-only; the generator itself also runs on Linux and macOS)
- Python 3.13 or newer (tested on 3.13)
- No internet connection required
- No external Python packages

## Quick start

### 1. Install Python

Install Python 3.13 or newer from [python.org](https://www.python.org/) and make sure `py` or `python` is available in `PATH`.

Check the installation:

```bash
python --version
```

### 2. Download the repository

```bash
git clone https://github.com/AcidOsint/pass_generator.git
cd pass_generator
```

### 3. Run Q3

On Windows, double-click `run.bat`, or run the package directly:

```bash
python -m q3pass
```

### 4. Generate a password

Choose **01 — GENERATE PASSWORD**. A password with the default settings appears immediately. Press `C` to copy it, `R` for a new one, or a number key to change the length.

Default settings: length 16, all four character classes, ambiguous characters excluded, at least one character of each class required.

## Main menu

| Option | Action |
|---|---|
| **01** | Generate a password with the current settings. |
| **02** | Change character classes, exclusions, clipboard auto-clear and hidden mode. |
| **03** | Show version, randomness source and limitations. |
| **04** | Exit. A pending clipboard clear is performed immediately and the console is cleared. |

## Generate screen

Single keys, no Enter needed.

| Key | Action |
|---|---|
| **R** | Generate a new password. |
| **C** | Copy the password to the clipboard. |
| **H** | Hide or show the password on screen. |
| **X** | Switch symbols on or off and generate a new password. |
| **1–6** | Set the length to 10 / 12 / 16 / 20 / 24 / 32 and generate a new password. |
| **L** | Enter a custom length from 8 to 64. |
| **S** | Open settings. |
| **B** | Back to the main menu. |

## Settings

| Key | Setting | Default |
|---|---|---|
| **1** | Lowercase `a-z` | ON |
| **2** | Uppercase `A-Z` | ON |
| **3** | Digits `0-9` | ON |
| **4** | Symbols (printable ASCII punctuation) | ON |
| **5** | Exclude ambiguous characters `0 O o 1 l I \|` | ON |
| **6** | Require at least one character of each enabled class | ON |
| **7** | Exclude custom characters (empty input clears the list) | none |
| **8** | Clear the clipboard 30 seconds after a copy | ON |
| **9** | Hide the password on screen | OFF |
| **D** | Reset the password settings to defaults (length is kept) | — |

An invalid change, such as disabling every class or excluding every digit, is rejected and the previous value is kept.

## How passwords are generated

- The alphabet is built from the enabled classes, minus ambiguous and custom-excluded characters.
- Every character is drawn independently and uniformly with `secrets.choice`.
- When required classes are on, a password missing any enabled class is discarded and a new one is drawn. This keeps the distribution uniform; the "one character from each class, then shuffle" shortcut does not.
- Entropy without required classes is `L × log2(N)`. With required classes, the number of valid passwords is counted exactly by inclusion–exclusion and the entropy is `log2` of that number.
- With the default settings the alphabet has 87 characters and a 16-character password has about **102.7 bits** of entropy.

## Clipboard

Q3 writes to the clipboard through the Win32 API and adds three formats that Windows recognises:

- `ExcludeClipboardContentFromMonitorProcessing`
- `CanIncludeInClipboardHistory = 0` — the password does not appear in Win+V history.
- `CanUploadToCloudClipboard = 0` — the password is not synced to other devices.

The privacy formats are placed first; if they cannot be set, the password is not copied at all.

Auto-clear remembers the clipboard sequence number of the copy. After 30 seconds the clipboard is emptied only if that number is unchanged, so anything you copied in the meantime is left alone. A new copy restarts the timer. After a clear, `CLIPBOARD CLEARED` appears in the status line on the next screen update.

## Important notes and limitations

- Q3 does not protect against a compromised system. Keyloggers, remote-access tools and malware can read the clipboard, memory or keystrokes.
- Hidden mode only hides the password from people looking at the screen or a screen share.
- A generated password exists in process memory and in the terminal while it is displayed. Python cannot reliably wipe strings from memory. Screens are cleared, including scrollback, when you navigate and on exit, but terminal recorders and PowerShell `Start-Transcript` keep everything.
- Windows honours the clipboard privacy formats; third-party clipboard managers may ignore them. Any program in your session can read the clipboard, including during the 30 seconds before auto-clear. Auto-clear works only while Q3 is running.
- Storing passwords is the job of a password manager. Q3 does not keep a copy.

## Tests

```bash
python -m unittest discover -s tests -t . -v
```

The statistical tests catch bugs in the mapping code, such as modulo bias or broken rejection sampling. They do not prove cryptographic strength; that rests on the OS generator.

The real clipboard tests overwrite your clipboard, so they run only on request:

```powershell
$env:Q3_CLIPBOARD_TEST="1"; python -m unittest tests.test_clipboard_win -v
```

### Manual checklist

1. `C`, then paste into Notepad — the password matches.
2. Win+V — the password does not appear in clipboard history.
3. Wait 30 seconds after `C` — paste gives nothing. Copy other text within 30 seconds — it survives.
4. `H` — the password is masked; `C` still pastes the real password.
5. Exit — the console window is cleared.
6. Hold the clipboard open in another program and press `C` — `CLIPBOARD BUSY` is shown, no crash.
7. Works in Windows Terminal and in the classic console (conhost).
8. Switch the keyboard layout to RU / UA — the keys still work.
9. `X` — symbols disappear from the password; `X` again brings them back.

## License

MIT License. See [`LICENSE`](LICENSE) for the full license text.
