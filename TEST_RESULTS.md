# Test results and limits

22 November 2026. Actual execution: Linux, Python 3.10.12, FFmpeg 4.4.2, faster-whisper 1.2.1, CTranslate2 4.9.1, Pillow 12.3.0, requests 2.34.2. No Windows machine or the user's laptop was used. Python 3.12 syntax parse passed, not equivalent to Windows execution. Cost: $0 in paid APIs/services.

## Sudais 13:28

- AlQuran Cloud returned audio URL: https://cdn.islamic.network/quran/audio/192/ar.abdurrahmaansudais/1735.mp3
- Text/English/audio API: https://api.alquran.cloud/v1/ayah/13:28/editions/quran-uthmani,en.sahih,ar.abdurrahmaansudais
- Ordinary local Whisper transcription omitted the repeated middle phrase. The final implementation does not interpolate it. It uses canonical-text local Whisper cross-attention/DTW alignment.
- All 11 spoken tokens mapped, no missing tokens; each forced-alignment token score >=0.2. This is a heuristic gate, not independently measured timing accuracy.
- Actual final file: 13.845 seconds, 2,698,251 bytes, H264 1080x1920 30/1fps, AAC. Original recitation preserved, no music, no 15-second force trim.
- Visual inspection: frames at 0.5, 3, 7, 10, 13.3 seconds. Full canonical Arabic centered in a fixed text group without a dark card, using text shadow, shaped and readable, cumulative Arabic gold through current word, English first/second clause switch at pause, surah/AYAH labels, final-second follow/reciter overlay without hiding the recitation text. English enlarged to44px and checked at390px phone width. Background intentionally fitted full-canvas with softened/lifted image fill.
- Background: generic mosque during sunrise, NOT verified as the Haram. Source page explicitly says public-domain CC0: https://www.rawpixel.com/image/5922699/photo-image-public-domain-free-islamic . Terms read: https://creativecommons.org/publicdomain/zero/1.0/ . Image metadata saved in sources.json. CC0 does not warrant that every contributor had all rights.
- Automatic stock search was tested and returned that image after earlier no-result/timeouts. Final regression render used the downloaded same image through --background-file for reproducibility.

## Maher 94:5-6

- Actual range audio concatenation, 5.467 seconds final MP4, approximately 0.5 MB, same H264/AAC/1080x1920/30fps.
- Strict default test correctly stopped on low-confidence word in 94:5, score 0.079577. Repeated local runs varied to0.1093 for this word; the final gate was made more conservative at0.2, not loosened to force a pass. Scores are not calibrated guarantees. No clean full-success claim.
- Explicit --allow-approximate render made for testing only. REVIEW in filename and visible on every frame, including second ayah. AYAH 5 changes to AYAH 6, English changes from 'For indeed...' to 'Indeed...', final-second overlay present.
- Background metadata: https://www.flickr.com/photos/38729417@N06/29379750356 , Public Domain Mark per Openverse. Original provider page rights not independently verified for this secondary test asset. Not supplied as a publication-approved asset.

A separate audio crop from6.92s to9.78s was inspected: the audio reader returned the omitted phrase (Ala bi-dhikr Allah), supporting the forced-alignment phrase interval. This is phrase-level cross-check evidence, not a human listen-check or independently measured per-word timing.

## Regression coverage

6 unit tests pass: exact canonical token mapping, missing-phrase rejection (no invented timings), Uthmani normalization, pause-ornament attachment with source text preserved, semantic clause switch, no arbitrary translation-halving.

Strict failures tested: low-confidence range alignment; stock-search no-result. These stop rather than silently deliver a gradient or made-up word timing.

## Still unverified

- Windows/Python 3.12 execution and device performance.
- All reciters/ayahs/descriptions. Per-ayah forced-alignment fallback is bounded to 28 seconds. Very long visual text stops instead of clipping.
- Exact millisecond timing accuracy. Whisper model probabilities are not calibrated proof of correctness.
- Audio redistribution/publication rights. Free API access is not verified permission to republish the recitation.
- Pixel-identical match to the user's laptop videos, which were not available.

This is a reusable, tested software deliverable with safe stop paths and explicit limitations, not a guarantee that every input produces a rights-cleared upload with no human review.

Style reference: https://github.com/asdd220977-svg/quran-reels-prompts . Its public text was used as reference only.
Font source verified matching SHA256: https://raw.githubusercontent.com/google/fonts/main/ofl/amiriquran/AmiriQuran-Regular.ttf . Font license: https://raw.githubusercontent.com/google/fonts/main/ofl/amiriquran/OFL.txt .

## Revision v3, 23 November 2026

User requested cumulative gold and no dark card. Both implemented in script and new render. Previous delivered file audited at0,.1,.5,1.3,2.3,3.3s: gold existed at0.0s, so the claimed2–3s visual delay was not reproduced. No global audio/timing shift was applied. New render audited at0,1.3,7.2,13.3s: cumulative highlight, no dark card, English clause change and outro remain.

Bounded audio check: crop0–1.2s returned first word (alladhina); crop1.2–2.22s returned second word (amanu), matching visual first and second highlight intervals. These are audio-reader checks, not human per-word listening or proof of exact synchronization. Full word timing remains approximate/model-based. Windows execution and audio publication rights remain unverified. Range strict failure remains a limitation, not forced into a clean pass.
