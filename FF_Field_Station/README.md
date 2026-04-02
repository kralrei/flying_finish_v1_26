# FF Field Station (Mobile Station App) 🏁

Aplikasi stasiun lapangan mandiri untuk **TC (Time Control)** dan **Start Line** yang terhubung langsung ke **Cloud PostgreSQL**.

## 🛠️ Persiapan Awal

1. **Backend Server**:
   Aplikasi mobile membutuhkan server perantara untuk menyimpan data ke database.
   - Jalankan `server.py` di PC atau Server:
     ```bash
     python server.py
     ```
   - Catat Alamat IP PC Anda (contoh: `192.168.1.10`).

2. **Akses dari Mobile**:
   - Buka file `index.html` di HP Anda (Lewat Browser).
   - ATAU Ubah URL API di `index.html` (baris 112) dari `127.0.0.1` ke Alamat IP PC Anda.

---

## 📱 Cara Membuat APK (Android)

Untuk mengubah aplikasi ini menjadi APK resmi, ikuti langkah berikut:

### Metode 1: Menggunakan Capacitor (Rekomendasi)

1. **Install Node.js & Capacitor**:
   ```bash
   npm init -y
   npm i @capacitor/core @capacitor/cli @capacitor/android
   npx cap init "FF Field Station" com.kralrei.ffstation
   ```

2. **Persiapkan Folder**:
   - Buat folder `www` dan pindahkan `index.html` ke dalamnya.
   - Tambahkan platform android:
     ```bash
     npx cap add android
     npx cap copy
     ```

3. **Build APK via Android Studio**:
   - Jalankan perintah:
     ```bash
     npx cap open android
     ```
   - Di Android Studio, klik **Build > Build Bundle(s) / APK(s) > Build APK(s)**.

### Metode 2: Website to APK (Paling Cepat)
Jika Anda menghosting `index.html` sebagai website (PWA), Anda bisa menggunakan layanan seperti [WebIntoApp](https://www.webintoapp.com/) untuk langsung mendapatkan file `.apk`.

---

## ⚙️ Fitur Aplikasi
- **Pemilihan SS**: (SS 1 - SS 30).
- **Mode Toggle**: Pindah antara stasiun **TC** dan **Start**.
- **Input NS**: Nomor Start peserta.
- **Input Jam**: Format modern HH:MM.
- **Neon UI**: Desain 2026 yang premium dan kontras tinggi untuk penggunaan outdoor.

---
*Kralrei Rally System &copy; 2026*
