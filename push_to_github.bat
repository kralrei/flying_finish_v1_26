@echo off
echo ========================================
echo   SYNCING KRALREI FLYING FINISH 2026
echo ========================================

:: 1. Ambil pesan dari user
set /p commit_msg="Masukkan pesan update: "
if "%commit_msg%"=="" set commit_msg=Update rutin

echo.
echo Menyiapkan file...
git add .

echo.
echo Membuat label perubahan...
:: Gunakan tanda kutip yang benar agar tidak error 'pathspec'
git commit -m "%commit_msg%"

echo.
echo Menarik data terbaru dari GitHub...
:: Tarik paksa data terbaru dari GitHub ke laptop
git pull --rebase origin main

echo.
echo Mengunggah ke GitHub...
:: Kirim semua perubahan ke GitHub
git push origin main

echo.
echo ========================================
echo   SELESAI! Laptop dan HP kini sinkron.
echo ========================================
pause
