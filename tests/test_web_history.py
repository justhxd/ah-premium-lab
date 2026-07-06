import json

from ha_backtest.web import HISTORY_METADATA_FILE, _history_page_runs, _history_record


def test_history_record_includes_akquant_report_metrics(tmp_path):
    output_dir = tmp_path / 'run_20250702_20260702_20260706_120000'
    output_dir.mkdir()
    q = chr(34)
    report_html = f'''
    <div class={q}metric-card{q}>
      <div class={q}metric-value positive{q}>12.34%</div>
      <div class={q}metric-label{q}>累计收益 (Total Return)</div>
    </div>
    <div class={q}metric-card{q}>
      <div class={q}metric-value positive{q}>9.87%</div>
      <div class={q}metric-label{q}>年化收益 (CAGR)</div>
    </div>
    <div class={q}metric-card{q}>
      <div class={q}metric-value negative{q}>-5.43%</div>
      <div class={q}metric-label{q}>最大回撤 (Max DD)</div>
    </div>
    <div class={q}metric-card{q}>
      <div class={q}metric-value{q}>1.23</div>
      <div class={q}metric-label{q}>夏普比率 (Sharpe)</div>
    </div>
    '''
    (output_dir / 'akquant_ha_report.html').write_text(report_html, encoding='utf-8')
    metadata = {
        'strategy': 'ha-premium',
        'createdAtIso': '2026-07-06T12:00:00',
        'startDate': '20250702',
        'endDate': '20260702',
        'initialCash': 1000000,
        'status': 'completed',
    }
    (output_dir / HISTORY_METADATA_FILE).write_text(json.dumps(metadata), encoding='utf-8')

    record = _history_record(output_dir)

    assert record is not None
    assert record['reportMetrics'] == {
        'totalReturn': '12.34%',
        'annualizedReturn': '9.87%',
        'maxDrawdown': '-5.43%',
        'sharpe': '1.23',
    }


def test_history_page_runs_excludes_missing_reports():
    runs = [
        {'id': 'run_ready', 'reportReady': True},
        {'id': 'run_missing', 'reportReady': False},
        {'id': 'run_unknown'},
    ]

    assert _history_page_runs(runs) == [{'id': 'run_ready', 'reportReady': True}]
