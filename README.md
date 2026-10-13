# Pedro IG autopost

Publishes the posts in `posts.csv` to @pedro.cardoso_personal.trainer via the official Instagram API.

- `posts.csv`: one row per post (date and time in Lisbon time, type, media file pattern, status).
- `captions/Pxx.txt`: the exact caption for each post.
- `media/`: put the reels (`P03.mp4` ...) and carousel images (`P01_01.png` ...) here.
- `publish.py`: the publisher. `.github/workflows/publish.yml` runs it every 5 minutes.
- `convert_images.py` + `convert-images.yml`: makes JPEG copies of PNGs (the API accepts JPEG only).

Secrets/variables needed (Settings > Secrets and variables > Actions):
- secret `IG_ACCESS_TOKEN`
- variable `PAGES_BASE_URL` (e.g. https://yourname.github.io/pedro-ig-autopost)

Status values: `pending` (will post), `published`, `missed` (more than 24 h late), `hold` (skipped).
Full setup guide: see the "Instagram API auto-posting setup guide" doc.
