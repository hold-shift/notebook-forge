# Why Notebook Forge exists — NotebookLM strips images of people

NotebookLM silently removes images that contain **identifiable people** during
source ingestion, while images of objects and landscapes in the *same* document
are processed fine. Because the images are stripped at ingestion, they can never
appear in NotebookLM's generated **slideshows, guides, or multimodal answers** —
which makes those features unusable for personal memoirs and historical
documents about people.

Notebook Forge works around this: it replaces each photo of a person with a
**faceless sketch** that passes ingestion, and links that sketch back to the
original photo hosted on your own site — so the people survive into the
generated output without their faces ever being published.

This page reproduces a community bug report describing the behaviour.

---

## Community bug report

> **Source:** NotebookLM Discord —
> <https://discord.com/channels/1124402182171672732/1495914924055068782>

I am experiencing a consistent issue where images containing identifiable people
are being stripped from my sources during ingestion, while images of
objects/landscapes (in the same document) are processed fine. This occurs
regardless of whether the source is a Google Doc or a direct PDF upload.

**The evidence (test results):**

- **Landscape/object images:** processed successfully (e.g. a photo of a brick
  viaduct).
- **Images of people:** completely stripped from the "Source Text" view; no
  `[Image]` placeholder is generated.
- **Privacy test:** I uploaded four versions of the same photo. The three
  versions with clear faces were stripped. The fourth version, where I pixelated
  the faces, was successfully ingested.
- **Multimodal failure:** when prompted to describe the image above a specific
  caption (which *is* ingested), the AI reports it "does not contain the actual
  image."

**Why this is an issue:**

This is not just a text-parsing tool; I am trying to use the slideshow / guide
generation features. If the images are stripped during ingestion, they cannot be
included in the generated output, rendering the multimodal features unusable for
personal memoirs or historical documents containing people.

**Steps taken:**

1. Set all images to "In Line."
2. Added descriptive alt text and anchor-text captions.
3. Compressed files to lower resolutions.
4. Tested via PDF direct upload to bypass Google Drive sync.

**Request:**

Can the team confirm whether this is intentional "safety filter" behaviour or a
bug in the multimodal ingestion pipeline? If intentional, is there a way to
"vouch" for personal/private documents so the AI can include these assets in
generated slideshows?
