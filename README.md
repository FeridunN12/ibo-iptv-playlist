# IBO Player IPTV Playlist

This project combines two public IPTV M3U playlists into one clean playlist for IBO Player.

Sources:

- Turkish: https://iptv-org.github.io/iptv/languages/tur.m3u
- Russian: https://iptv-org.github.io/iptv/countries/ru.m3u

The generated playlist is written to:

```text
docs/combined.m3u
```

The output keeps Turkish channels first, Russian channels second, skips empty lines, removes duplicate stream URLs, and preserves each `#EXTINF` line with its stream URL.

## Run Locally

```bash
python combine.py
```

## Automatic Updates

The GitHub Actions workflow in `.github/workflows/update.yml` runs once per day and can also be started manually from the Actions tab. It runs `combine.py`, then commits any updated `docs/combined.m3u` file back to the repository.

## Push To GitHub

Create a new empty repository on GitHub, then run these commands from this project folder:

```bash
git init
git add .
git commit -m "Initial IPTV playlist combiner"
git branch -M main
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/YOUR_REPO_NAME.git
git push -u origin main
```

Replace `YOUR_GITHUB_USERNAME` and `YOUR_REPO_NAME` with your real GitHub username and repository name.

## Enable GitHub Pages

1. Open your repository on GitHub.
2. Go to **Settings**.
3. Go to **Pages**.
4. Under **Build and deployment**, set **Source** to **Deploy from a branch**.
5. Set **Branch** to `main`.
6. Set the folder to `/docs`.
7. Click **Save**.

After GitHub Pages finishes publishing, your public playlist URL will be:

```text
https://YOUR_GITHUB_USERNAME.github.io/YOUR_REPO_NAME/combined.m3u
```

Paste that final URL into IBO Player.
