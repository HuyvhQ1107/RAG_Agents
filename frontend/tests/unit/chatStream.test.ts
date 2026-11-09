import { describe, expect, it } from 'vitest';
import { parseSseChunk } from '../../src/services/chatStream';

describe('SSE Chat Stream Parser', () => {
  it('parses turn.started, status, answer.delta, citations, and turn.completed frames', () => {
    const rawSse = [
      'event: turn.started',
      'data: {"conversation_id":"c1","user_turn_id":"u1","assistant_turn_id":"a1","trace_id":"t1"}',
      '',
      'event: status',
      'data: {"stage":"retrieving","message":"Đang tìm kiếm tài liệu..."}',
      '',
      'event: answer.delta',
      'data: {"text":"Nhân viên chính thức được nghỉ 12 ngày phép năm [1]."}',
      '',
      'event: citations',
      'data: {"items":[{"marker":1,"citation_id":"cit1","document_id":"d1","document_title":"Quy định nghỉ phép","version_number":1,"section_path":"Điều 4","page_start":1,"page_end":1,"quote_snippet":"12 ngày nghỉ phép năm"}]}',
      '',
      'event: turn.completed',
      'data: {"assistant_turn_id":"a1","kind":"answer","language":"vi","latency_ms":420,"Partial":false}',
      '',
    ].join('\n');

    const events = parseSseChunk(rawSse);
    expect(events).toHaveLength(5);
    expect(events[0].event).toBe('turn.started');
    expect(events[2].event).toBe('answer.delta');
    expect((events[2].data as any).text).toContain('12 ngày');
    expect(events[3].event).toBe('citations');
    expect((events[3].data as any).items[0].marker).toBe(1);
    expect(events[4].event).toBe('turn.completed');
  });
});
