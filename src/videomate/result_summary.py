"""Small immutable outcome views built from closed, validated session exports."""
from collections import Counter

from .errors import MESSAGES
from .private_state import report_pages
from .schema import load_json, validate_export


def summarize(encoded):
    actions, video, states, reasons, issues, losses = (Counter() for _ in range(6))
    summary = None
    for page in report_pages(encoded):
        document = load_json(page)
        validate_export(document)
        summary = document.get('migration_summary', summary)
        for entry in document['files']:
            migration = entry.get('migration', {})
            action = migration.get('action', entry['integrity'])
            actions[action] += 1
            if migration.get('input_kind') == 'video':
                video[action] += 1
            states[entry['recovery_state']] += 1
            for loss in set(entry.get('losses', [])):
                losses[loss] += 1
            if action in {'excluded_unresolved', 'failed', 'copied_unresolved', 'retained_for_review'}:
                codes = {step['error_code'] for step in entry.get('diagnostics', []) if step['error_code'] != 'none'}
                if not codes:
                    codes = {a['reason'] for a in entry['attempts'] if a['reason'] != 'none'}
                if not codes:
                    codes = {migration.get('reason', 'recovery_unverified')}
                reasons.update(codes)
                issues.update({issue for a in entry['attempts'] for issue in a.get('verification_issues', [])})
    state = summary['state'] if summary else 'unknown'
    title = {'needs_review': 'Finished with omissions, partial or unresolved files — review needed',
             'incomplete': 'Incomplete — review required', 'interrupted': 'Interrupted — review required',
             'complete': 'Finished — verified repairs include loss disclosures' if states['verified_with_losses'] else 'Finished'}.get(state, 'Inspection / recovery results')
    lines = [title]
    if summary:
        s = summary
        lines += [f"Processed {s['processed_files']:,}/{s['planned_files']:,}; published {s['published_files']:,}; partial {s.get('partial_files', 0):,}; excluded {s['excluded_files']:,}; failed {s['failed_files']:,}; not processed {s['unprocessed_files']:,}."]
    if video:
        lines.append(f"Videos: {sum(video.values()):,}; healthy copies {video['copied_healthy']:,}; repaired {video['repaired']:,}; partial {video['salvaged_partial']:,}; excluded {video['excluded_unresolved']:,}; failed {video['failed']:,}.")
    if summary and (hardware := summary.get('hardware')):
        lines.append(f"Hardware decode: {hardware['decode_selection']}; integrity checks: software. Peak simultaneous hardware jobs: {hardware['peak_gpu_jobs']}; active route slots: {hardware['peak_active_routes']}.")
        for route in hardware['routes']:
            lines.append(f"  Route {route['slot']}: {route['decoder']} / {route['encoder']}; peak jobs {route['peak_jobs']}.")
    lines += [f"{k.replace('_', ' ')}: {v:,}" for k, v in states.items() if k != 'not_requested']
    if reasons:
        lines.append('Unresolved causes (affected files; categories can overlap):')
        lines += [f"  {key}: {n:,}. {MESSAGES.get(key, key.replace('_', ' '))}" for key, n in reasons.most_common()]
    if issues:
        lines.append('Verification disagreements (affected files; can overlap):')
        lines += [f"  {k}: {v:,}" for k, v in issues.most_common()]
    if losses:
        lines.append('Published repair disclosures (not necessarily visible defects):')
        lines += [f"  {k}: {v:,}" for k, v in losses.most_common()]
    return {'title': title, 'text': '\n'.join(lines), 'summary': summary,
            'unresolved': sum(actions[k] for k in ('excluded_unresolved', 'failed', 'copied_unresolved', 'retained_for_review'))}
