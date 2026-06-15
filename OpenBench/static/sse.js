(function () {
    if (!window.EventSource) return;

    var source = new EventSource('/api/sse/');

    source.addEventListener('message', function (e) {
        if (!e.data) return;

        var update;
        try {
            update = JSON.parse(e.data);
        } catch (err) {
            return;
        }

        var testId = String(update.test_id);

        if (update.finished && document.querySelector('[data-test-id="' + testId + '"]')) {
            location.reload();
            return;
        }

        var colour = update.colour || '';

        var shortHtml = '<strong>' + escapeHtml(update.short_stat_block).replace(/\n/g, '<br>') + '</strong>';
        document.querySelectorAll('[data-test-id="' + testId + '"][data-statblock="short"]').forEach(function (el) {
            el.className = 'statblock statblock-' + colour;
            el.innerHTML = shortHtml;
        });

        var longHtml = escapeHtml(update.long_stat_block).replace(/\n/g, '<br>');
        document.querySelectorAll('[data-test-id="' + testId + '"][data-statblock="long"]').forEach(function (el) {
            el.innerHTML = longHtml;
        });

        if (window.refreshLlrHistoryWidget) {
            window.refreshLlrHistoryWidget(testId);
        }
    });

    function escapeHtml(text) {
        return text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }
}());
