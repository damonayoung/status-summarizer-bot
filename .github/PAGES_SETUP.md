# GitHub Pages Setup Guide

## 📋 Prerequisites

Before the "Publish Executive Brief to Pages" workflow can run successfully, you need to configure two things:

---

## 1. Add OpenAI API Key Secret

The workflow needs your OpenAI API key to generate fresh reports.

### Steps:

1. Go to your repository on GitHub
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Name: `OPENAI_API_KEY`
5. Value: Your OpenAI API key (starts with `sk-...`)
6. Click **Add secret**

**Security Note:** Never commit your API key to the repository. GitHub Secrets are encrypted and only accessible during workflow runs.

---

## 2. Enable GitHub Pages

### Steps:

1. Go to your repository on GitHub
2. Click **Settings** → **Pages** (in the left sidebar)
3. Under **Source**, select:
   - Source: **GitHub Actions** (not "Deploy from a branch")
4. Click **Save**

### Verify Configuration:

After the workflow runs successfully, your Pages site will be available at:
```
https://<your-username>.github.io/<repository-name>/
```

Example: `https://dayfornight.github.io/status-summarizer-bot/`

---

## 🚀 How the Workflow Works

### Automatic Triggers

The workflow runs automatically when:
- You push code to the `main` branch
- You manually trigger it via "Actions" tab → "Publish Executive Brief to Pages" → "Run workflow"

### What It Does

1. **Checks out** your repository code
2. **Sets up Python 3.13** environment
3. **Installs dependencies** from `requirements.txt`
4. **Generates fresh report** by running `python src/main_v2.py`
5. **Finds latest HTML** in the `output/` directory
6. **Deploys to GitHub Pages** as `index.html`

### Workflow Steps Explained

```yaml
# Generate fresh executive report
- Uses your OPENAI_API_KEY secret
- Runs the multi-source summarizer (main_v2.py)
- Creates HTML report in output/ directory
- If generation fails, continues to deployment (graceful degradation)

# Prepare site for deployment
- Finds most recent HTML file: ls -t output/*.html
- Copies to public/index.html for Pages
- If no files found, creates helpful placeholder page

# Deploy to GitHub Pages
- Uploads public/ directory as Pages artifact
- Deploys to your Pages site
```

---

## 📊 Expected Results

### Successful Deployment

After the workflow completes:
1. Visit your GitHub Pages URL
2. You should see your latest executive status report
3. The report will be beautifully formatted with:
   - At-a-glance dashboard
   - Color-coded status indicators
   - Risk tables
   - Stakeholder pulse
   - Metrics and trends

### If Report Generation Fails

If the OpenAI API call fails (quota exceeded, invalid key, etc.):
- The workflow will show a warning but continue
- It will deploy the most recent existing HTML file
- If no HTML files exist, it will deploy a placeholder page explaining setup steps

---

## 🔧 Troubleshooting

### "No reports generated yet" placeholder shows

**Possible causes:**
1. `OPENAI_API_KEY` secret not set → Add it in repository settings
2. API key is invalid → Verify key is correct and active
3. API quota exceeded → Check OpenAI account billing
4. No HTML files in `output/` directory → Run `python src/main_v2.py` locally first

**Quick fix:**
```bash
# Generate a report locally and commit it
python src/main_v2.py
git add output/weekly_summary_*.html
git commit -m "Add initial report for Pages"
git push
```

### Workflow fails on "Generate fresh executive report" step

**Check:**
1. GitHub Actions logs: Repository → Actions → Latest workflow run
2. Look for OpenAI API errors in the "Generate fresh executive report" step
3. Verify `OPENAI_API_KEY` secret is set correctly

**Note:** The workflow uses `continue-on-error: true` for report generation, so even if this step fails, deployment will continue with existing files.

### "404 Not Found" when visiting Pages URL

**Possible causes:**
1. GitHub Pages not enabled → Check Settings → Pages
2. Workflow hasn't run yet → Trigger manually or push to main
3. Deployment still in progress → Wait 1-2 minutes after workflow completes

---

## 🎨 Customization

### Change Report Source

By default, the workflow runs `src/main_v2.py` (multi-source executive format).

To use a different script:
```yaml
- name: Generate fresh executive report
  run: |
    python src/main.py  # Simple version
```

### Change Model

The workflow uses `gpt-4o` by default. To use a cheaper model:

```yaml
- name: Generate fresh executive report
  env:
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
    OPENAI_MODEL: gpt-4o-mini  # Cheaper alternative
  run: |
    python src/main_v2.py
```

### Deploy Specific File

To always deploy a specific file instead of the latest:

```yaml
- name: Prepare site for deployment
  run: |
    mkdir -p public
    cp output/summary_sample2.html public/index.html
```

---

## 📈 Monitoring

### View Workflow Runs

1. Go to your repository on GitHub
2. Click the **Actions** tab
3. Select "Publish Executive Brief to Pages" workflow
4. View run history, logs, and deployment status

### Check Pages Deployment

1. Go to Settings → Pages
2. See "Your site is live at..." message
3. Click the URL to view deployed site

---

## 💰 Cost Considerations

### OpenAI API Usage

Each workflow run that generates a report will:
- Call OpenAI API once (multi-source summarization)
- Cost approximately $0.01-$0.05 per run (with gpt-4o)
- Monthly cost: ~$1-5 (if running weekly)

**Cost Optimization:**
- Use `gpt-4o-mini` model instead (10x cheaper)
- Only generate reports weekly instead of on every push
- Use schedule trigger instead of push trigger

### Scheduled Reports Example

To generate reports only on Fridays at 5pm:

```yaml
on:
  schedule:
    - cron: '0 17 * * 5'  # Every Friday at 5pm UTC
  workflow_dispatch:
```

---

## ✅ Checklist

Before expecting the workflow to succeed:

- [ ] `OPENAI_API_KEY` added to repository secrets
- [ ] GitHub Pages enabled with source "GitHub Actions"
- [ ] At least one push to main branch after setup
- [ ] Workflow run completed successfully
- [ ] Pages deployment shows "Active" status
- [ ] Pages URL loads without 404 error

---

## 🎉 Success!

Once configured, your GitHub Pages site will automatically update with fresh executive status reports every time you push to main!

**Your team can bookmark the Pages URL** and always see the latest program status without running any code locally.

---

*For issues or questions, see the main [README.md](../README.md) or [ARCHITECTURE.md](../ARCHITECTURE.md)*
