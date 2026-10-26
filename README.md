# REEZ - Offline Personal AI Assistant

REEZ is a personal AI assistant that runs fully on your own laptop. It answers questions from your own files, listens and speaks, reads hand gestures through the webcam, and keeps an encrypted locker for private notes and files. No cloud AI services are used.

## Features

- **Ask your documents:** reads PDF, Word, PowerPoint, Excel, HTML, text and code files (Retrieval-Augmented Generation with LangChain, ChromaDB and Ollama)
- **Exact lists:** resumes are split into sections, so skills, certificates, projects and education come out exactly, with the document name first and a clickable list of source files
- **Voice:** always-listening wake word ("REEZ"), speech recognition with faster-whisper, a natural offline voice (Piper)
- **Understanding:** fixes mistakes, remembers follow-up questions, understands typed Tamil-English (Tanglish)
- **Hand gestures:** OpenCV and MediaPipe wake REEZ and adjust volume, voice speed and scrolling by hand movement
- **Encrypted locker:** AES-GCM with a code word and a master word, decrypted only in memory, auto-locks
- **Desktop app:** PySide6 window with a floating icon, quick chat window, drag and drop

## Requirements

- Windows 10 or 11, Python 3.12
- [Ollama](https://ollama.com) installed and running
- About 16 GB of RAM is comfortable; a microphone and webcam are optional

## Setup

Setup: https://setup-reez.netlify.app

The speech models download by themselves the first time the microphone is used.

## Document

Document: https://document-reez.netlify.app

## Run

Put your files in the `docs` folder (or drag them onto the chat). On first run you choose your own folder name, code word and master word for the locker. They are never stored in the code.

## Privacy

Everything runs locally. The locker is encrypted on disk; your documents, locker and settings are not part of this repository.

## Known Limits

- Speech recognition on a laptop microphone is the weakest part; a headset microphone helps a lot
- A small local model takes a few seconds per answer on a laptop processor
- Scanned PDFs and photos are stored but not read

## Author

Balamurali Krishna VKS

Built as a solo project.
