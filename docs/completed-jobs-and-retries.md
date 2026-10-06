# Completed jobs and unresolved retries

Version 0.8.4 includes a persistent result card, grouped reasons, same-session continuation after Stop and a session-only unresolved retry. Export any wanted memory-only diagnostics before closing the app.

## Read the outcome

Processed means the input was handled, not that it was successfully recovered. Finished with omissions remains visible after reviewing or exporting. Video counts are separate from other files. Review findings lists affected-file counts for fixed refusal reasons, verification disagreements and repair losses. Categories can overlap. `salvaged_partial` is published in the main package and counted separately; the package needs review. `verified_with_losses` can include lossy encoding, metadata removal, timing/track changes and possible concealment; it is not a promise that the original recording was restored.

Preview, summary and export feedback no longer replaces finished counts or progress. The result retains its processing policy when options for a later job change. The activity pane is a bounded tail; it labels truncation and stops following while scrolled away. The explicit log export reports its generated basename and uses the Diagnostics folder configured when that job started. No export or sharing occurs automatically in Sensitive mode.

## Retry exclusions and failures

For memory-only jobs completed with interruption recovery enabled:

1. Keep the app open. Select the same source folder and output root locally.
2. Review reasons, then adjust only the settings that address them. Verification remains mandatory.
3. Click **Preview unresolved retry** to compare previous/requested policies and the unresolved count. Preview inventories the selection; content/output verification occurs at execution.
4. Click **Start unresolved retry**. Changing settings or selection requires another preview.

The existing package is reused. New migrations place files directly in an empty destination; retry returns to that owned destination. Older versioned packages keep their historical layout. Completed source/output contents must match before reuse; missing or changed completed outputs stop the retry. Previously excluded/failed inputs are processed with the new policy. Verified copies and repairs, including marked partial recoveries, are preserved without re-encoding. Already published unchanged unresolved/review copies are retained; this action does not overwrite or replace them. Originals are untouched. To try improving an already published partial file, create a separate new migration or Repair job rather than overwriting it in place.

The matching snapshot is held only in memory: a random key, keyed name/stat/root/content tokens, authenticated sanitized result records and neutral output kinds. It contains no source paths or filenames and writes no new restart history or mappings. Up to eight snapshots are kept; closing the app discards them. Content checks can require substantial disk reads even though completed files are not re-encoded. A diagnostic log cannot reconstruct this private matching state, so old jobs cannot be retroactively attached to this feature.

After **Stop**, use **Continue stopped migration** on Start or Activity while the app is still open. Reselect the same source and output and retain the original recovery policy; no preview is required. Existing publications are verified and unpublished work is resumed. **Start new migration** creates a new job and therefore requires an empty destination. Closing the app discards the memory-only continuation snapshot.

Optional private restart checkpoints are a separate workflow requiring the original policy, Job ID and passphrase. A private-checkpoint job uses that checkpoint for restart; it does not create a separate session retry snapshot whose later changes could diverge from persisted state. The diagnostic log cannot serve as either snapshot.

## Size and hardware choices

Existing saved settings retain `strict` size behavior. New MP4 presets choose `best_effort`: try one bitrate adjustment, then permit an oversized result only if full independent verification passes. Missing/unusable size estimates fall back to Auto and are disclosed. Strict withholds results still above tolerance. Neither mode relaxes disk limits, source checks, decoding, timing or track-preservation checks. CLI: `--size-policy strict` or `--size-policy best_effort`.

Hardware summaries distinguish a requested decoder from a qualified route and actual peak admitted hardware work. They include job-scoped route slots, decoder/encoder enums and simultaneous job/route counts, without device names, driver text or stable adapter identifiers. Software integrity inspection remains intentional. A software repair decoder can reflect unavailable qualification or a failed combined route. Route slots are not proof of distinct physical GPUs across vendor APIs. NVIDIA has explicit device routing; AMD/Intel still use qualified default adapters. Native Mac and physical multi-GPU performance qualification remain outstanding.
