name: Monthly update

on:
  schedule:
    - cron: "0 5 1 * *"
  workflow_dispatch:
  push:
    branches: [main]

permissions:
  contents: write
  pages: write
  id-token: write

jobs:
  update:
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deploy.outputs.page_url }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install lxml==5.3.0
      - name: Fetch every source, normalise, build the site
        run: python tracker.py
      - name: Save updated data to the repository
        run: |
          git config user.name "tracker-bot"
          git config user.email "tracker-bot@users.noreply.github.com"
          git add data site raw ref
          git diff --cached --quiet || git commit -m "Data update $(date +%Y-%m-%d)"
          git push
      - uses: actions/upload-pages-artifact@v3
        with:
          path: site
      - id: deploy
        uses: actions/deploy-pages@v4
