@echo off
echo ========================================
echo   SYNCING KRALREI FLYING FINISH 2026
echo ========================================

:: 1. Berikan label untuk perubahan Anda
set /p commit_msg="Masukkan pesan update (contoh: Perbaikan bug): "

:: Jika pesan kosong, beri default
if "%commit_msg%"=="" set commit_msg="Update rutin"

echo.
echo Sedang menyiapkan file...
git add .

echo.
echo Sedang membuat label perubahan...
git commit -m "%commit_msg%"

echo.
echo Sedang menarik data terbaru dari GitHub...
git pull --rebase

echo.
echo Sedang mengunggah ke GitHub...
git push

echo.
echo ========================================
echo   SELESAI! Update berhasil diunggah.
echo ========================================
pause
