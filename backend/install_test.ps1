$packages = "fastapi", "uvicorn", "websockets", "webrtcvad-wheels", "python-multipart", "python-dotenv", "openai", "deepgram-sdk", "elevenlabs"
foreach ($pkg in $packages) {
    Write-Host "Installing $pkg"
    .\venv\Scripts\python -m pip install $pkg
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed to install $pkg"
        exit 1
    }
}
Write-Host "All installed successfully"
