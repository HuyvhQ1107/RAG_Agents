import React, { useEffect, useState } from 'react';
import {
  AdminDocumentItem,
  AdminGroupItem,
  deleteAdminDocument,
  listAdminDocuments,
  listAdminGroups,
  updateAdminDocument,
  uploadAdminDocuments,
} from '../services/api';

export const AdminDocumentsPage: React.FC = () => {
  const [documents, setDocuments] = useState<AdminDocumentItem[]>([]);
  const [groups, setGroups] = useState<AdminGroupItem[]>([]);
  const [files, setFiles] = useState<FileList | null>(null);
  const [isCompanyWide, setIsCompanyWide] = useState<boolean>(false);
  const [selectedGroups, setSelectedGroups] = useState<string[]>([]);
  const [effectiveFrom, setEffectiveFrom] = useState<string>('');
  const [expiresOn, setExpiresOn] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [uploading, setUploading] = useState<boolean>(false);

  const loadData = async () => {
    try {
      const [docRes, grpRes] = await Promise.all([listAdminDocuments(), listAdminGroups()]);
      setDocuments(docRes.items);
      setGroups(grpRes.items.filter((g) => !g.deleted_at));
    } catch (err: any) {
      setError(err.message || 'Không thể tải danh sách tài liệu.');
    }
  };

  useEffect(() => {
    void loadData();
  }, []);

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setNotice(null);

    if (!files || files.length === 0) {
      setError('Vui lòng chọn ít nhất 1 tệp tài liệu (PDF, DOCX, HTML, MD).');
      return;
    }
    if (files.length > 20) {
      setError('Chỉ được tải lên tối đa 20 tệp mỗi lần.');
      return;
    }
    if (!isCompanyWide && selectedGroups.length === 0) {
      setError('Phải chọn ít nhất 1 phòng ban hoặc đánh dấu Tài liệu toàn công ty.');
      return;
    }

    setUploading(true);
    try {
      const res = await uploadAdminDocuments({
        files: Array.from(files),
        is_company_wide: isCompanyWide,
        group_ids: selectedGroups,
        effective_from: effectiveFrom || undefined,
        expires_on: expiresOn || undefined,
      });
      setNotice(`Đã xử lý ${res.items.length} tài liệu.`);
      setFiles(null);
      await loadData();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setUploading(false);
    }
  };

  const handleToggleCompanyWide = async (doc: AdminDocumentItem) => {
    setError(null);
    try {
      await updateAdminDocument(doc.id, {
        is_company_wide: !doc.is_company_wide,
        group_ids: doc.groups.map((g) => g.id),
      });
      setNotice(`Đã cập nhật phạm vi phân quyền cho tài liệu "${doc.title}".`);
      await loadData();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleDelete = async (docId: string, title: string) => {
    setError(null);
    try {
      await deleteAdminDocument(docId);
      setNotice(`Đã gỡ tài liệu "${title}".`);
      await loadData();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const statusBadgeColor = (status: string) => {
    switch (status) {
      case 'ready':
        return { bg: '#dcfce7', fg: '#166534' };
      case 'expired':
      case 'failed':
      case 'removed':
        return { bg: '#fee2e2', fg: '#991b1b' };
      case 'scheduled':
        return { bg: '#fef3c7', fg: '#92400e' };
      default:
        return { bg: '#e0f2fe', fg: '#075985' };
    }
  };

  return (
    <div style={{ padding: '24px', maxWidth: '1150px', margin: '0 auto' }}>
      <h2 style={{ marginTop: 0, fontSize: '20px', fontWeight: 700, marginBottom: '16px' }}>
        Quản trị Tài liệu Nội bộ & Phân quyền
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
      {notice && (
        <div
          style={{
            padding: '12px',
            background: '#ecfdf5',
            border: '1px solid #a7f3d0',
            color: '#047857',
            borderRadius: '8px',
            marginBottom: '16px',
          }}
        >
          {notice}
        </div>
      )}

      <form
        onSubmit={handleUpload}
        style={{
          border: '1px solid #cbd5e1',
          borderRadius: '10px',
          padding: '18px',
          background: '#fff',
          marginBottom: '28px',
        }}
      >
        <h3 style={{ marginTop: 0, fontWeight: 600, marginBottom: '12px' }}>
          Tải lên lô tài liệu mới (1–20 tệp, tối đa 50 MB/tệp)
        </h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
          <div>
            <label style={{ display: 'block', fontSize: '13px', fontWeight: 600, marginBottom: '6px' }}>
              Chọn tệp (PDF có lớp văn bản, DOCX, HTML, Markdown):
            </label>
            <input
              type="file"
              multiple
              accept=".pdf,.docx,.html,.htm,.md,.markdown"
              onChange={(e) => setFiles(e.target.files)}
              style={{ marginBottom: '12px' }}
            />
            <div style={{ display: 'flex', gap: '12px', marginTop: '8px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '12px', color: '#475569' }}>
                  Ngày hiệu lực (Effective From):
                </label>
                <input
                  type="date"
                  value={effectiveFrom}
                  onChange={(e) => setEffectiveFrom(e.target.value)}
                  style={{ padding: '6px', borderRadius: '6px', border: '1px solid #cbd5e1' }}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '12px', color: '#475569' }}>
                  Ngày hết hạn (Expires On):
                </label>
                <input
                  type="date"
                  value={expiresOn}
                  onChange={(e) => setExpiresOn(e.target.value)}
                  style={{ padding: '6px', borderRadius: '6px', border: '1px solid #cbd5e1' }}
                />
              </div>
            </div>
          </div>

          <div>
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600, fontSize: '14px' }}>
              <input
                type="checkbox"
                checked={isCompanyWide}
                onChange={(e) => setIsCompanyWide(e.target.checked)}
              />
              Công khai toàn công ty (Company-wide)
            </label>
            <p style={{ fontSize: '12px', color: '#64748b', margin: '6px 0 10px' }}>
              Hoặc giới hạn cho các phòng ban cụ thể:
            </p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
              {groups.map((g) => (
                <label key={g.id} style={{ fontSize: '13px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <input
                    type="checkbox"
                    checked={selectedGroups.includes(g.id)}
                    onChange={(e) =>
                      setSelectedGroups((prev) =>
                        e.target.checked ? [...prev, g.id] : prev.filter((id) => id !== g.id)
                      )
                    }
                  />
                  {g.name}
                </label>
              ))}
            </div>
          </div>
        </div>
        <button
          type="submit"
          disabled={uploading}
          style={{
            marginTop: '16px',
            padding: '10px 20px',
            background: '#2563eb',
            color: '#fff',
            border: 'none',
            borderRadius: '6px',
            cursor: 'pointer',
            fontWeight: 600,
          }}
        >
          {uploading ? 'Đang xử lý & băm tài liệu...' : 'Tải lên & Lập chỉ mục'}
        </button>
      </form>

      <h3 style={{ fontWeight: 600, marginBottom: '10px' }}>Danh mục Tài liệu</h3>
      <table style={{ width: '100%', borderCollapse: 'collapse', background: '#fff', fontSize: '13px' }}>
        <thead>
          <tr style={{ background: '#f8fafc', textAlign: 'left', borderBottom: '2px solid #e2e8f0' }}>
            <th style={{ padding: '10px' }}>Tiêu đề</th>
            <th style={{ padding: '10px' }}>Trạng thái hiển thị</th>
            <th style={{ padding: '10px' }}>Phân quyền</th>
            <th style={{ padding: '10px' }}>Hiệu lực</th>
            <th style={{ padding: '10px' }}>Số phiên bản</th>
            <th style={{ padding: '10px' }}>Thao tác</th>
          </tr>
        </thead>
        <tbody>
          {documents.map((doc) => {
            const badge = statusBadgeColor(doc.display_status);
            return (
              <tr key={doc.id} style={{ borderBottom: '1px solid #e2e8f0' }}>
                <td style={{ padding: '10px', fontWeight: 600 }}>
                  {doc.title}
                  {doc.latest_error_code && (
                    <div style={{ color: '#dc2626', fontSize: '11px', fontWeight: 400 }}>
                      Mã lỗi: {doc.latest_error_code} — {doc.latest_error_detail}
                    </div>
                  )}
                </td>
                <td style={{ padding: '10px' }}>
                  <span
                    style={{
                      padding: '3px 8px',
                      borderRadius: '999px',
                      fontSize: '12px',
                      fontWeight: 600,
                      background: badge.bg,
                      color: badge.fg,
                    }}
                  >
                    {doc.display_status}
                  </span>
                </td>
                <td style={{ padding: '10px' }}>
                  {doc.is_company_wide ? (
                    <span style={{ color: '#0284c7', fontWeight: 600 }}>Toàn công ty</span>
                  ) : (
                    doc.groups.map((g) => g.name).join(', ') || (
                      <span style={{ color: '#dc2626' }}>Không có nhóm (Cô lập)</span>
                    )
                  )}
                </td>
                <td style={{ padding: '10px', fontSize: '12px' }}>
                  Từ: {doc.effective_from || '—'}
                  <br />
                  Đến: {doc.expires_on || '—'}
                </td>
                <td style={{ padding: '10px' }}>{doc.version_count} phiên bản</td>
                <td style={{ padding: '10px', display: 'flex', gap: '6px' }}>
                  <button
                    type="button"
                    onClick={() => void handleToggleCompanyWide(doc)}
                    style={{
                      padding: '4px 8px',
                      background: '#f8fafc',
                      border: '1px solid #cbd5e1',
                      borderRadius: '4px',
                      cursor: 'pointer',
                      fontSize: '12px',
                    }}
                  >
                    Đổi phạm vi
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleDelete(doc.id, doc.title)}
                    style={{
                      padding: '4px 8px',
                      background: '#fee2e2',
                      color: '#b91c1c',
                      border: '1px solid #fca5a5',
                      borderRadius: '4px',
                      cursor: 'pointer',
                      fontSize: '12px',
                    }}
                  >
                    Xóa
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};
