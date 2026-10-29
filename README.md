# Kryšpova univerzita

```
content/departments/<slug>/index.md   a department (title, emoji, color, summary + intro text)
content/departments/<slug>/*.md       its posts (front matter: title, date, summary, info)
content/pages/*.md                    plain pages (/about/ ...)
content/staff.yaml                    staff list (name, role, optional department slug)
static/images/posts/                  inline post images
```

Posts live at `/departments/<slug>/<post-slug>/`. A new department is just a new folder with an `index.md`.

Images: drop a file into `static/images/posts/` and reference it in Markdown:

```markdown
![Alt text](/static/images/posts/some-image.jpg)
```

Build and preview: `pip install -r requirements.txt && python build.py --serve`
