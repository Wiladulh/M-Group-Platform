# Memori Proyek — Direktori docs/

Direktori `docs/` adalah **memori proyek**: tempat keputusan, pemahaman spesifikasi, asumsi, kontrak teknis, dan progres implementasi dipelihara agar pekerjaan konsisten lintas sesi dan kontributor.

## Aturan wajib sebelum setiap langkah
1. Baca `m-group-platform-spec.md` di root sebagai **Single Source of Truth** jika konteks atau keputusan baseline perlu diverifikasi.
2. Baca `docs/UNDERSTANDING.md` untuk arsitektur, keputusan kritis, area ambigu, dan checklist langkah.
3. Baca `docs/ASSUMPTIONS.md` sebelum mengambil keputusan pada hal yang belum dirinci.
4. Baca `docs/PROGRESS.md` untuk mengetahui fase terakhir, status gerbang, hasil tes, dan commit.
5. Baca dokumen teknis terkait fase yang sedang dikerjakan (misalnya API, DB schema, WebSocket, hardware, security, deployment, atau WebUI).

**Setiap langkah kerja wajib membaca docs/ terlebih dahulu sebelum mengubah repo.** Perbarui dokumen terkait pada langkah yang sama saat keputusan, kontrak, asumsi, atau status fase berubah.

## Prioritas sumber
1. `m-group-platform-spec.md` — aturan dan spesifikasi produk yang mengikat.
2. Dokumen teknis di `docs/` — rincian implementasi yang konsisten dengan baseline.
3. `docs/ASSUMPTIONS.md` — pilihan eksplisit untuk hal yang belum ditentukan.
4. `docs/PROGRESS.md` — catatan status pekerjaan; bukan pengganti kriteria penerimaan.

Jika dokumen teknis bertentangan dengan baseline, jangan mengubah baseline secara diam-diam. Catat konflik dan pilih opsi paling aman sesuai aturan kerja Section 0.
