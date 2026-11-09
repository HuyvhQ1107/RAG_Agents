import React, { useEffect, useState } from 'react';
import {
  FeedbackQueueItem,
  getOpsMetricsSummary,
  getOpsTurnTrace,
  listNegativeFeedback,
  OpsMetricsSummary,
} from '../services/api';

export const OpsPage: React.FC = () => {
  const [metrics, setMetrics] = useState<OpsMetricsSummary | null>(null);
  const [feedbackItems, setFeedbackItems] = useState<FeedbackQueueItem[]>([]);
  const [selectedTrace, setSelectedTrace] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadData = async () => {
    try {
      const [m, f] = await Promise.all([getOpsMetricsSummary(), listNegativeFeedback()]);
      setMetrics(m);
      setFeedbackItems(f.items);
    } catch (err: any) {
      setError(err.message || 'Không thể tải số liệu vận hành.');
    }
  };

  useEffect(() => {
    void loadData();
  }, []);

  const handleInspectTrace = async (turnId: string) => {
    try {
      const trace = await getOpsTurnTrace(turnId);
      setSelectedTrace(trace);
    } catch (err: any) {
      setError(err.message);
    }
  };

  return (
    <div style={{ padding: '24px', maxWidth: '1150px', margin: '0 auto' }}>
      <h2 style={{ marginTop: 0, fontSize: '20px', fontWeight: 700, marginBottom: '16px' }}>
        Bảng điều khiển Vận hành (Ops) & Truy vết Agent
      </h2>

      {error && (
        <div
          style={{
            padding: '12px',
            background: '#fef2f2',
            border: '1px solid #fecaca',
            color: '#b91c1c',
            borderRadius: '8px',
            marginBottom: '16px',
          }}
        >
          {error}
        </div>
      )}

      {metrics && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(4, 1fr)',
            gap: '16px',
            marginBottom: '28px',
          }}
        >
          <div style={{ padding: '16px', background: '#fff', border: '1px solid #e2e8f0', borderRadius: '10px' }}>
            <div style={{ fontSize: '12px', color: '#64748b' }}>Tổng lượt hỏi đáp</div>
            <div style={{ fontSize: '24px', fontWeight: 700, marginTop: '4px' }}>{metrics.total_turns}</div>
            <div style={{ fontSize: '12px', color: '#475569', marginTop: '4px' }}>
              Chi phí ước tính: ${metrics.total_cost_usd.toFixed(4)}
            </div>
          </div>

          <div style={{ padding: '16px', background: '#fff', border: '1px solid #e2e8f0', borderRadius: '10px' }}>
            <div style={{ fontSize: '12px', color: '#64748b' }}>Độ trễ toàn trình (p50 / p95)</div>
            <div style={{ fontSize: '24px', fontWeight: 700, marginTop: '4px' }}>
              {metrics.latency_p50_ms}ms / {metrics.latency_p95_ms}ms
            </div>
            <div style={{ fontSize: '12px', color: '#475569', marginTop: '4px' }}>
              TTFT p50 / p95: {metrics.ttft_p50_ms}ms / {metrics.ttft_p95_ms}ms
            </div>
          </div>

          <div style={{ padding: '16px', background: '#fff', border: '1px solid #e2e8f0', borderRadius: '10px' }}>
            <div style={{ fontSize: '12px', color: '#64748b' }}>Tỷ lệ Làm rõ / Không tìm thấy</div>
            <div style={{ fontSize: '24px', fontWeight: 700, marginTop: '4px' }}>
              {(metrics.clarification_rate * 100).toFixed(1)}% / {(metrics.not_found_rate * 100).toFixed(1)}%
            </div>
            <div style={{ fontSize: '12px', color: '#475569', marginTop: '4px' }}>
              Tỷ lệ lỗi: {(metrics.error_rate * 100).toFixed(1)}%
            </div>
          </div>

          <div style={{ padding: '16px', background: '#fff', border: '1px solid #e2e8f0', borderRadius: '10px' }}>
            <div style={{ fontSize: '12px', color: '#64748b' }}>Đánh giá Hữu ích (Helpful)</div>
            <div style={{ fontSize: '24px', fontWeight: 700, marginTop: '4px', color: '#0284c7' }}>
              {(metrics.helpful_feedback_rate * 100).toFixed(1)}%
            </div>
            <div style={{ fontSize: '12px', color: '#475569', marginTop: '4px' }}>
              Tổng phản hồi: {metrics.total_feedback_count}
            </div>
          </div>
        </div>
      )}

      <h3 style={{ fontWeight: 600, marginBottom: '10px' }}>Danh sách Phản hồi Người dùng (Đã ẩn danh PII)</h3>
      <table style={{ width: '100%', borderCollapse: 'collapse', background: '#fff', fontSize: '13px' }}>
        <thead>
          <tr style={{ background: '#f8fafc', textAlign: 'left', borderBottom: '2px solid #e2e8f0' }}>
            <th style={{ padding: '10px' }}>Thời gian</th>
            <th style={{ padding: '10px' }}>Đánh giá</th>
            <th style={{ padding: '10px' }}>Câu hỏi (Đã che PII)</th>
            <th style={{ padding: '10px' }}>Ghi chú (Đã che PII)</th>
            <th style={{ padding: '10px' }}>Hành vi lượt chat</th>
            <th style={{ padding: '10px' }}>Truy vết</th>
          </tr>
        </thead>
        <tbody>
          {feedbackItems.map((item) => (
            <tr key={item.id} style={{ borderBottom: '1px solid #e2e8f0' }}>
              <td style={{ padding: '10px' }}>{new Date(item.created_at).toLocaleString('vi-VN')}</td>
              <td style={{ padding: '10px', fontWeight: 600 }}>{item.rating}</td>
              <td style={{ padding: '10px' }}>{item.masked_question}</td>
              <td style={{ padding: '10px' }}>{item.comment || '—'}</td>
              <td style={{ padding: '10px' }}>{item.kind}</td>
              <td style={{ padding: '10px' }}>
                <button
                  type="button"
                  onClick={() => void handleInspectTrace(item.turn_id)}
                  style={{
                    padding: '4px 10px',
                    background: '#eff6ff',
                    color: '#1d4ed8',
                    border: '1px solid #bfdbfe',
                    borderRadius: '4px',
                    cursor: 'pointer',
                  }}
                >
                  Xem Trace
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {selectedTrace && (
        <div
          style={{
            marginTop: '24px',
            padding: '18px',
            background: '#0f172a',
            color: '#f8fafc',
            borderRadius: '10px',
            fontFamily: 'monospace',
            fontSize: '12px',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
            <strong>Chi tiết TurnTrace (Đã ẩn danh PII) — Turn ID: {selectedTrace.turn_id}</strong>
            <button
              type="button"
              onClick={() => setSelectedTrace(null)}
              style={{
                background: 'transparent',
                color: '#94a3b8',
                border: '1px solid #475569',
                borderRadius: '4px',
                cursor: 'pointer',
                padding: '2px 8px',
              }}
            >
              Đóng
            </button>
          </div>
          <pre style={{ overflowX: 'auto', margin: 0 }}>{JSON.stringify(selectedTrace, null, 2)}</pre>
        </div>
      )}
    </div>
  );
};
