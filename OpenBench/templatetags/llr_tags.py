import html
import json

from django import template
from django.utils.safestring import mark_safe

import OpenBench.utils
import OpenBench.llr_history

register = template.Library()
def llr_history_graph(test, width=340, height=120):

    ## Render the LLR-over-games series as a standalone inline SVG. Doing this
    ## server-side keeps the workload page free of charting dependencies, and
    ## lets the graph render before any JavaScript runs. The hover readout is
    ## wired up in workload.html, using the JSON we stash on the wrapper.

    if test.test_mode != 'SPRT':
        return ''

    history = list(OpenBench.llr_history.load_llr_history(test))

    # The series always starts at the origin, and ends at the present
    if not history or history[0][0] != 0:
        history.insert(0, [0, 0.0])
    if history[-1][0] != test.games or history[-1][1] != test.currentllr:
        history.append([test.games, test.currentllr])

    x_max = max(max(p[0] for p in history), 1)

    # Center 0.00 vertically, and pad out past the widest observed value
    observed = max(abs(test.lowerllr), abs(test.upperllr), max(abs(p[1]) for p in history))
    extent   = max(observed * 1.15, 0.5)
    y_min, y_max = -extent, extent

    L, R, T, B = 8, 8, 8, 8
    iw, ih = max(width - L - R, 1), max(height - T - B, 1)

    sx = lambda v : L + iw * (v / x_max)
    sy = lambda v : T + ih * (1.0 - (v - y_min) / (y_max - y_min))

    points = [{
        'g' : p[0], 'l' : round(p[1], 4),
        'x' : round(sx(p[0]), 2), 'y' : round(sy(p[1]), 2),
    } for p in history]

    # How far a sample has travelled toward the bound it is heading for, 0..1.
    # The colour is a function of this alone, so the same LLR always draws the
    # same colour and neighbouring samples never disagree about their hue.
    #
    # Only the flat stretch within +-0.1 of zero reads as yellow. Past it the
    # exponent bends the ramp hard, so the line finds its green or its red
    # well before the LLR gets anywhere near a bound.
    LLR_NEUTRAL = 0.1

    def travel(p):
        bound = abs(test.upperllr if p['l'] >= 0.0 else test.lowerllr)
        room  = bound - LLR_NEUTRAL
        if room <= 0.0: return 0.0
        return min(max(abs(p['l']) - LLR_NEUTRAL, 0.0) / room, 1.0) ** 0.35

    # Green above zero, red below: the sign is the whole of the hue, and the
    # distance from zero is the whole of the strength. The neutral they both
    # fade into is the yellow, not a grey -- an undecided test still reads as
    # a colour on the same ramp rather than as a dead line.
    def band(p):
        if travel(p) < 0.40: return 'yellow'
        return 'pos' if p['l'] >= 0.0 else 'neg'

    # Carried in the payload so the hover dot lands on the same colour as the
    # stretch of line under it, without the readout having to know the bounds
    for p in points:
        p['b'] = band(p)

    ## The line is one polyline stroked with a gradient carrying a stop per
    ## sample, rather than a run of flat-coloured segments meeting at hard
    ## edges. Each stop's colour is read off the smoothed LLR alone: green
    ## above zero, red below, deepening out of the yellow as the curve commits
    ## to the bound it is heading for. The colour is a position on that one
    ## ramp, so it moves with the curve rather than flipping about.
    ##
    ## The mix is left to CSS so the palette stays in the stylesheet; the class
    ## on each stop is the flat fallback, used if color-mix is unavailable.

    grad_id = 'llr-grad-%d' % (test.id)

    def stop_color(p):
        return 'color-mix(in srgb, var(--llr-%s) %d%%, var(--llr-yellow))' % (
            'pos' if p['l'] >= 0.0 else 'neg', round(100 * travel(p)))

    def stop(p):
        return '<stop class="llr-stop-%s" offset="%.5f" style="stop-color: %s"/>' % (
            band(p), (p['x'] - points[0]['x']) / span, stop_color(p))

    span     = max(points[-1]['x'] - points[0]['x'], 1e-6)
    drawable = len(points) >= 2 and points[-1]['x'] > points[0]['x']

    gradient = '' if not drawable else (
        '<linearGradient id="%s" gradientUnits="userSpaceOnUse" '
        'x1="%.2f" y1="0" x2="%.2f" y2="0">%s</linearGradient>' % (
            grad_id, points[0]['x'], points[-1]['x'],
            ''.join(stop(p) for p in points)))

    path = '' if not drawable else (
        '<polyline class="llr-path" stroke="url(#%s)" points="%s"/>' % (
            grad_id, ' '.join('%.2f,%.2f' % (p['x'], p['y']) for p in points)))

    guides = []
    for v, name in ((test.lowerllr, 'llr-bound'), (0.0, 'llr-zero'), (test.upperllr, 'llr-bound')):
        guides.append('<line class="%s" x1="%d" y1="%.2f" x2="%d" y2="%.2f"/>' % (
            name, L, sy(v), width - R, sy(v)))
        if name == 'llr-bound':
            guides.append('<text class="llr-bound-label" x="%d" y="%.2f">%+.2f</text>' % (
                L + 4, sy(v) + (11.0 if v > 0 else -3.5), v))

    last      = points[-1]
    last_band = band(last)
    clip_id   = 'llr-reveal-%d' % (test.id)

    halo = '' if test.finished else (
        '<circle class="llr-endpoint-halo llr-fill-%s" cx="%.2f" cy="%.2f" r="2.8"/>' % (
            last_band, last['x'], last['y']))

    return mark_safe((
        '<div class="llr-history-widget" data-history="%s">'
          '<div class="llr-history-chart">'
            '<div class="llr-history-main">'
              '<div class="llr-history-plot">'
                '<svg class="llr-history-graph" viewBox="0 0 %d %d" preserveAspectRatio="none" role="img" aria-label="%s">'
                  '<defs>%s<clipPath id="%s"><rect class="llr-reveal" x="0" y="0" width="%d" height="%d"/></clipPath></defs>'
                  '<rect class="llr-bg" x="0" y="0" width="%d" height="%d"/>'
                  '%s'
                  '<g clip-path="url(#%s)">%s</g>'
                  '<g class="llr-endpoint-grp">%s'
                    '<circle class="llr-endpoint llr-fill-%s" cx="%.2f" cy="%.2f" r="2.8"/>'
                  '</g>'
                  '<line class="llr-hover-line" x1="%.2f" y1="%d" x2="%.2f" y2="%d"/>'
                  '<circle class="llr-hover-point" cx="%.2f" cy="%.2f" r="3.2"/>'
                  '<rect class="llr-hitbox" x="0" y="0" width="%d" height="%d"/>'
                '</svg>'
                '<div class="llr-history-tooltip"></div>'
              '</div>'
            '</div>'
          '</div>'
        '</div>'
    ) % (
        html.escape(json.dumps(points, separators=(',', ':'))),
        width, height,
        html.escape('LLR %.2f after %d games' % (test.currentllr, test.games)),
        gradient, clip_id, width, height,
        width, height,
        ''.join(guides),
        clip_id, path,
        halo, last_band, last['x'], last['y'],
        last['x'], T, last['x'], height - B,
        last['x'], last['y'],
        width, height,
    ))

register.filter('llr_history_graph', llr_history_graph)


