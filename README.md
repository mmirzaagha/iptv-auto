# Avtomatik IPTV sistemi

## Necə işləyir
- `base.m3u` sənin əl ilə yazdığın siyahıdır. Eyni kanalı bir neçə dəfə yazsan (fərqli linklərlə), hamısı ehtiyat sayılır.
- `sources.txt`-dəki açıq siyahılardan eyni adlı kanalların əlavə linkləri avtomatik tapılır.
- GitHub Actions hər 30 dəqiqədən bir bütün linkləri yoxlayır və `0130.m3u` faylını yenidən yazır.
- Cloudflare Worker isə izləyəndə (`0130-live.m3u`) işləyən linki anında seçib yönləndirir.

## Quraşdırma (bir dəfəlik)

### 1. GitHub
1. Repoda (`0130`) bu faylları kök qovluğa yüklə: `build.py`, `sources.txt`, `aliases.json`.
2. Hazırkı `0130.m3u` faylının surətini `base.m3u` adı ilə yüklə. Bundan sonra kanalı əl ilə `base.m3u`-ya əlavə edirsən, `0130.m3u`-ya toxunma (avtomatik yazılır).
3. `update.yml` faylını `.github/workflows/update.yml` yoluna qoy.
4. Repo Settings -> Actions -> General -> Workflow permissions: **Read and write permissions** seç.
5. Actions bölməsində `update-playlist` -> **Run workflow** düyməsini bas. 1-2 dəqiqəyə `0130.m3u`, `channels.json`, `report.md` yenilənəcək.

Bu mərhələdə sistem artıq işləyir: Televizo-da köhnə link (`.../0130/0130.m3u`) qalır.

### 2. Cloudflare Worker (kəsintisiz üçün)
1. dash.cloudflare.com -> Workers & Pages -> Create -> Hello World -> Deploy -> Edit code.
2. `worker.js` məzmununu yapışdır, Deploy et.
3. Worker -> Settings -> Variables: `DATA_URL` = `https://mmirzaagha.github.io/0130/channels.json`
4. Worker linkini (məsələn `https://iptv.sənin-ad.workers.dev`) götür.
5. GitHub repo -> Settings -> Secrets and variables -> Actions -> **Variables** -> `WORKER_URL` = həmin link (sonunda `/` olmadan).
6. Workflow-u yenidən işlət. `0130-live.m3u` yaranacaq, Televizo-ya bu linki əlavə et:
   `https://mmirzaagha.github.io/0130/0130-live.m3u`

## Gündəlik istifadə
- `report.md` faylına bax: hansı kanalın heç bir linki işləmir. Ona `base.m3u`-ya yeni link əlavə et.
- Yeni GitHub siyahısı bağlamaq: raw m3u linkini `sources.txt`-ə yaz.
- Kanal adı fərqli yazılıbsa və tapılmırsa, `aliases.json`-a `"mənbədəki ad": "base.m3u-dakı ad"` əlavə et.

## Məhdudiyyətlər
- GitHub serverləri xaricdədir. Azərbaycana bağlı (geo-blok) linklər orada "ölü" görünə bilər. Belə linklər silinmir, siyahının sonunda qalır və Worker onları Cloudflare tərəfdən yenidən yoxlayır.
- Müddəti bitmiş tokenli linklər (`?e=...&st=...`) yoxlamada düşəcək. Onları yenisi ilə əvəz et.
