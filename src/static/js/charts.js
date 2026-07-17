/**
 * OreX Price Chart — ApexCharts with time range filters, datetime x-axis,
 * and gap detection for market inactivity periods.
 *
 * Active trading periods render as a solid colored line.
 * Inactivity gaps render as a dashed grey connector between segments.
 */
(function () {
    'use strict';

    var dataElement = document.getElementById('price-data');
    var chartContainer = document.getElementById('price-chart');
    var apiUrlElement = document.getElementById('chart-api-url');
    if (!dataElement || !chartContainer) return;

    var priceData;
    try {
        priceData = JSON.parse(dataElement.textContent);
    } catch (e) {
        return;
    }

    var apiUrl = apiUrlElement ? JSON.parse(apiUrlElement.textContent) : null;

    var currentRange = '5m';
    var chart = null;

    // Expose chart instance for external use (e.g., R/S annotations)
    window.getOreChart = function () { return chart; };

    // Gap threshold in milliseconds — scales with selected range
    var GAP_THRESHOLDS = {
        '5m': 2 * 60 * 1000,
        '15m': 3 * 60 * 1000,
        '30m': 5 * 60 * 1000,
        '1h': 5 * 60 * 1000,
        '6h': 10 * 60 * 1000,
        '12h': 15 * 60 * 1000,
        '1d': 30 * 60 * 1000,
        '3d': 2 * 60 * 60 * 1000,
        '5d': 4 * 60 * 60 * 1000,
        'max': 6 * 60 * 60 * 1000
    };

    function getGapThreshold() {
        return GAP_THRESHOLDS[currentRange] || 5 * 60 * 1000;
    }

    function getLineColour(data) {
        if (data.length < 2) return '#2ecc71';
        var firstPrice = null;
        var lastPrice = null;
        for (var i = 0; i < data.length; i++) {
            if (data[i][1] !== null) { firstPrice = data[i][1]; break; }
        }
        for (var j = data.length - 1; j >= 0; j--) {
            if (data[j][1] !== null) { lastPrice = data[j][1]; break; }
        }
        if (firstPrice === null || lastPrice === null) return '#2ecc71';
        return lastPrice >= firstPrice ? '#2ecc71' : '#e74c3c';
    }

    /**
     * Convert raw API data into two series:
     * - "active": solid line for normal trading periods (nulls during gaps)
     * - "gap": dashed grey line bridging inactive periods (nulls during active)
     */
    function buildSeries(data) {
        if (!data || data.length === 0) return { active: [], gap: [] };

        var gapThreshold = getGapThreshold();
        var active = [];
        var gap = [];

        for (var i = 0; i < data.length; i++) {
            var ts = new Date(data[i].time).getTime();
            var price = data[i].price;

            if (i === 0) {
                active.push([ts, price]);
                gap.push([ts, null]);
                continue;
            }

            var prevTs = new Date(data[i - 1].time).getTime();
            var timeDiff = ts - prevTs;

            if (timeDiff > gapThreshold) {
                // End of previous active segment — add bridge points to gap series
                var prevPrice = data[i - 1].price;

                // Close active segment with null to break the line
                active.push([prevTs + 1, null]);

                // Gap connector: from last active point to this new point
                gap.push([prevTs, prevPrice]);
                gap.push([ts, price]);

                // Start new active segment
                active.push([ts, price]);
                gap.push([ts + 1, null]);
            } else {
                // Normal active point
                active.push([ts, price]);
                gap.push([ts, null]);
            }
        }

        return { active: active, gap: gap };
    }

    function renderChart(data) {
        var series = buildSeries(data);
        var lineColour = getLineColour(series.active);

        var hasGaps = series.gap.some(function (p) { return p[1] !== null; });

        var chartSeries = [
            { name: 'Price', data: series.active }
        ];

        var chartColors = [lineColour];

        var strokeConfig = {
            curve: 'smooth',
            width: [3],
            dashArray: [0]
        };

        if (hasGaps) {
            chartSeries.push({ name: 'Inactive', data: series.gap });
            chartColors.push('#555555');
            strokeConfig.width = [3, 2];
            strokeConfig.dashArray = [0, 5];
            strokeConfig.curve = ['smooth', 'straight'];
        }

        var options = {
            chart: {
                type: 'line',
                height: 400,
                background: 'transparent',
                toolbar: { show: false },
                zoom: { enabled: false },
                animations: { enabled: false }
            },
            colors: chartColors,
            series: chartSeries,
            dataLabels: { enabled: false },
            stroke: strokeConfig,
            xaxis: {
                type: 'datetime',
                labels: {
                    style: { colors: '#4a3968', fontSize: '10px', fontWeight: 600 },
                    datetimeUTC: false,
                    datetimeFormatter: {
                        year: 'yyyy',
                        month: 'MMM yyyy',
                        day: 'dd MMM',
                        hour: 'HH:mm'
                    }
                },
                axisBorder: { color: '#c4b8d9' },
                axisTicks: { color: '#c4b8d9' }
            },
            yaxis: {
                labels: {
                    style: { colors: '#4a3968', fontSize: '11px', fontWeight: 600 },
                    formatter: function (val) {
                        if (val === null || val === undefined) return '';
                        return '$' + val.toFixed(2);
                    }
                }
            },
            grid: { borderColor: '#c4b8d9', strokeDashArray: 3 },
            tooltip: {
                theme: 'light',
                x: { format: 'dd MMM yyyy HH:mm' },
                y: {
                    formatter: function (val) {
                        if (val === null || val === undefined) return '';
                        return '$' + val.toFixed(2);
                    }
                }
            },
            legend: { show: false },
            markers: { size: 0, hover: { size: 5 } },
            theme: { mode: 'light' },
            noData: {
                text: 'No data for this range',
                style: { color: '#6b5f7a', fontSize: '14px' }
            }
        };

        if (chart) {
            chart.destroy();
        }
        chart = new ApexCharts(chartContainer, options);
        chart.render();

        // Notify external scripts (e.g., R/S annotations) that chart was re-rendered
        window.dispatchEvent(new CustomEvent('oreChartRendered'));
    }

    // Initial render — fetch 5m data from API if available, otherwise use embedded data
    if (apiUrl) {
        fetch(apiUrl + '?range=' + currentRange)
            .then(function (res) { return res.json(); })
            .then(function (data) {
                renderChart(data && data.length > 0 ? data : []);
            })
            .catch(function () {
                renderChart(priceData && priceData.length > 0 ? priceData : []);
            });
    } else if (priceData && priceData.length > 0) {
        renderChart(priceData);
    } else {
        renderChart([]);
    }

    // Filter button handlers
    var filters = document.getElementById('chart-filters');
    if (filters && apiUrl) {
        filters.addEventListener('click', function (e) {
            var btn = e.target.closest('.chart-filter');
            if (!btn) return;

            var range = btn.dataset.range;

            // Update active state
            filters.querySelectorAll('.chart-filter').forEach(function (b) {
                b.classList.remove('chart-filter--active');
            });
            btn.classList.add('chart-filter--active');

            // Fetch new data
            currentRange = range;
            fetch(apiUrl + '?range=' + range)
                .then(function (res) { return res.json(); })
                .then(function (data) {
                    renderChart(data);
                })
                .catch(function (err) {
                    console.error('Failed to load chart data:', err);
                });
        });
    }

    // Auto-refresh chart every 20 seconds with current filter
    if (apiUrl) {
        setInterval(function () {
            fetch(apiUrl + '?range=' + currentRange)
                .then(function (res) { return res.json(); })
                .then(function (data) {
                    if (data.length > 0) {
                        renderChart(data);
                    }
                })
                .catch(function () {});
        }, 20000);
    }
})();
