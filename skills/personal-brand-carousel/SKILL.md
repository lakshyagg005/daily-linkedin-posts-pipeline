# Personal Brand Carousel Engine

## Purpose

Generate one high-quality 7-slide LinkedIn carousel for Lakshya's personal brand.

The carousel should feel:
- intelligent
- research-backed
- visually premium
- concise
- useful
- modern
- founder/tech-builder oriented

The goal is quality, not content volume.

Never copy Founders Wing branding, language, identity, assets, or calls-to-action.

---

# Core Output

Every carousel must contain exactly:

1. Slide 1 — Hook
2. Slide 2 — Context / What changed
3. Slide 3 — The misunderstood part
4. Slide 4 — Evidence / Data / Example
5. Slide 5 — Why it matters
6. Slide 6 — Builder takeaway
7. Slide 7 — Final insight + CTA

Output:

- 7 PNG slides
- 1080 × 1080 px
- 1 PDF containing the 7 PNG slides

---

# Brand Positioning

Lakshya is building a personal brand around:

- AI
- software
- startups
- building products
- technology
- entrepreneurship
- learning in public
- practical business lessons
- interesting technology trends
- creator economy
- automation

The content should be written from the perspective of a young builder learning, experimenting and building.

Do NOT fabricate:
- startup revenue
- users
- customers
- personal achievements
- experiments
- experiences
- statistics

If something is not known, do not present it as personal experience.

---

# Content Principles

## 1. One Big Idea

Each carousel must communicate one central idea.

Do not combine unrelated topics.

Bad:

"AI + startups + coding + productivity + motivation"

Good:

"Why AI wrappers are becoming less defensible"

---

## 2. Strong Hook

Slide 1 must create curiosity immediately.

Avoid generic hooks such as:

- "5 things you need to know"
- "Here are 7 AI trends"
- "Want to be successful?"
- "AI is changing everything"

Prefer:

- surprising observations
- counterintuitive claims
- specific numbers
- strong questions
- useful contradictions

Example:

"Most AI startups aren't really AI companies."

---

## 3. Research Before Writing

For factual or current topics, research first.

Prioritize:

1. Primary sources
2. Company documentation
3. Official statistics
4. Research papers
5. High-quality journalism
6. Industry reports

Do not invent statistics.

Every important numerical or factual claim should have a source available in the research notes.

---

# Slide Architecture

## Slide 1 — HOOK

Purpose:

Stop scrolling.

Requirements:

- 1 major statement
- maximum 1 supporting sentence
- very large typography
- minimal visual clutter

---

## Slide 2 — CONTEXT

Explain what is happening.

Use:

- short paragraphs
- numbers
- timeline
- comparison
- simple diagram

The reader should understand the situation within 5 seconds.

---

## Slide 3 — MISUNDERSTANDING

Explain what most people get wrong.

Structure:

"Most people think X.

But the important part is Y."

This slide should create an information gap.

---

## Slide 4 — EVIDENCE

Show evidence.

Possible formats:

- statistic
- chart
- screenshot
- timeline
- comparison
- product example
- research finding

Do not overload the slide.

---

## Slide 5 — WHY IT MATTERS

Translate the evidence into an implication.

Answer:

"So what?"

Connect the topic to:

- builders
- founders
- creators
- developers
- students
- businesses

depending on the topic.

---

## Slide 6 — BUILDER TAKEAWAY

Give practical action.

Use 2–4 concise points.

Example:

"If I were building in this market today:

1. Start with distribution.
2. Build a workflow, not just a wrapper.
3. Own the user relationship."

Do not make this generic motivational advice.

---

## Slide 7 — FINAL INSIGHT

End with one memorable idea.

Possible structure:

"The opportunity isn't disappearing.

The easy opportunity is."

Then a small CTA:

"Follow for more practical AI + startup breakdowns."

CTA must remain subtle.

---

# Visual Design

Canvas:

1080 × 1080 px

Style:

- premium editorial
- modern tech
- strong typography
- generous whitespace
- visual hierarchy
- minimal decoration

Avoid:

- generic AI gradients
- excessive glassmorphism
- random 3D objects
- emoji-heavy design
- stock-photo collage
- tiny text
- overcrowded slides
- fake dashboard screenshots

---

# Typography

Use a strong modern sans-serif for primary text.

Optional:

Use a serif italic accent for 1–2 words when it improves hierarchy.

Typography hierarchy:

1. Main headline
2. Supporting statement
3. Evidence/data
4. Small source/metadata

Never make body text too small.

---

# Colors

Base:

- warm off-white / cream
- black / near-black typography

Use one accent color per carousel.

Possible accents:

- electric blue
- lime
- orange
- violet
- red

Do not use many accent colors simultaneously.

---

# Sources

If a slide contains research-based information, include a small source label.

Example:

"Source: OpenAI, 2026"

or:

"Source: Stanford AI Index, 2026"

Sources should be readable but visually secondary.

Do not place giant URLs on slides.

Full URLs belong in research metadata or the LinkedIn caption when useful.

---

# File Structure

The generated carousel should use:

carousel-routine/temp/personal-brand/

for temporary HTML slides.

Rendered images should go to:

carousel-routine/output/YYYY-MM-DD/personal-brand/

The renderer already exists in:

carousel-routine/render.js

PDF generation already exists in:

carousel-routine/render-pdf.js

Do not create a new rendering engine.

---

# Rendering Process

After generating all 7 HTML slides:

Run:

```bash
node carousel-routine/render.js YYYY-MM-DD personal-brand