import React, { useEffect, useState } from 'react';
import {
  AdminGroupItem,
  AdminUserItem,
  createAdminGroup,
  createAdminUser,
  deleteAdminGroup,
  listAdminGroups,
  listAdminUsers,
  resetAdminUserPassword,
  updateAdminUser,
} from '../services/api';

export const AdminUsersPage: React.FC = () => {
  const [users, setUsers] = useState<AdminUserItem[]>([]);
  const [groups, setGroups] = useState<AdminGroupItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // New user form
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [roles, setRoles] = useState<string[]>(['employee']);
  const [selectedGroups, setSelectedGroups] = useState<string[]>([]);

  // New group form
  const [groupName, setGroupName] = useState('');
  const [groupDescription, setGroupDescription] = useState('');

  const loadData = async () => {
    try {
      const [uRes, gRes] = await Promise.all([listAdminUsers(), listAdminGroups()]);
      setUsers(uRes.items);
      setGroups(gRes.items);
    } catch (err: any) {
      setError(err.message || 'Không thể tải danh sách người dùng và phòng ban.');
    }
  };

  useEffect(() => {
    void loadData();
  }, []);

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setNotice(null);
    try {
      const res = await createAdminUser({
        username,
        display_name: displayName,
        email: email || undefined,
        roles,
        group_ids: selectedGroups,
      });
      setUsername('');
      setEmail('');
      setDisplayName('');
      setRoles(['employee']);
      setSelectedGroups([]);
      setNotice(
        `Đã tạo tài khoản "${res.user.username}". Mật khẩu tạm thời (1 lần): ${res.temporary_password}`
      );
      await loadData();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleToggleUserStatus = async (user: AdminUserItem) => {
    setError(null);
    setNotice(null);
    const nextStatus = user.status === 'active' ? 'disabled' : 'active';
    try {
      await updateAdminUser(user.id, { status: nextStatus });
      setNotice(
        nextStatus === 'disabled'
          ? `Đã vô hiệu hóa ${user.username} và thu hồi mọi phiên đăng nhập.`
          : `Đã kích hoạt lại tài khoản ${user.username}.`
      );
      await loadData();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleResetPassword = async (user: AdminUserItem) => {
    setError(null);
    setNotice(null);
    try {
      const res = await resetAdminUserPassword(user.id);
      setNotice(`Đã cấp mật khẩu tạm thời mới cho ${user.username}: ${res.temporary_password}`);
      await loadData();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleCreateGroup = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setNotice(null);
    try {
      await createAdminGroup({
        name: groupName,
        description: groupDescription || undefined,
      });
      setGroupName('');
      setGroupDescription('');
      setNotice('Đã tạo nhóm / phòng ban mới.');
      await loadData();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleDeleteGroup = async (groupId: string, groupTitle: string) => {
    setError(null);
    setNotice(null);
    try {
      const res = await deleteAdminGroup(groupId);
      if (res.orphaned_document_ids.length > 0) {
        setNotice(
          `Đã xóa mềm phòng ban "${groupTitle}". Cảnh báo: Có ${res.orphaned_document_ids.length} tài liệu hiện không còn nhóm truy cập hoạt động (KHÔNG tự động chuyển thành công khai toàn công ty).`
        );
      } else {
        setNotice(`Đã xóa mềm phòng ban "${groupTitle}".`);
      }
      await loadData();
    } catch (err: any) {
      setError(err.message);
    }
  };

  return (
    <div style={{ padding: '24px', maxWidth: '1150px', margin: '0 auto' }}>
      <h2 style={{ marginTop: 0, fontSize: '20px', fontWeight: 700, marginBottom: '16px' }}>
        Quản trị Người dùng & Phòng ban (RBAC)
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

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px', marginBottom: '28px' }}>
        <form
          onSubmit={handleCreateUser}
          style={{ border: '1px solid #e2e8f0', borderRadius: '10px', padding: '16px', background: '#fff' }}
        >
          <h3 style={{ marginTop: 0, fontWeight: 600, marginBottom: '12px' }}>Tạo tài khoản nhân viên</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <input
              type="text"
              placeholder="Tên đăng nhập (vd: emp_fin)"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              style={{ padding: '8px', borderRadius: '6px', border: '1px solid #cbd5e1' }}
            />
            <input
              type="text"
              placeholder="Họ và tên hiển thị"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              required
              style={{ padding: '8px', borderRadius: '6px', border: '1px solid #cbd5e1' }}
            />
            <input
              type="email"
              placeholder="Email nhân viên (tùy chọn)"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              style={{ padding: '8px', borderRadius: '6px', border: '1px solid #cbd5e1' }}
            />
            <div>
              <label style={{ fontSize: '13px', fontWeight: 600 }}>Vai trò:</label>
              <div style={{ display: 'flex', gap: '12px', marginTop: '4px' }}>
                {['employee', 'content_admin', 'operator', 'admin'].map((r) => (
                  <label key={r} style={{ fontSize: '13px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <input
                      type="checkbox"
                      checked={roles.includes(r)}
                      onChange={(e) =>
                        setRoles((prev) =>
                          e.target.checked ? [...prev, r] : prev.filter((item) => item !== r)
                        )
                      }
                    />
                    {r}
                  </label>
                ))}
              </div>
            </div>
            <div>
              <label style={{ fontSize: '13px', fontWeight: 600 }}>Phòng ban trực thuộc:</label>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', marginTop: '4px' }}>
                {groups
                  .filter((g) => !g.deleted_at)
                  .map((g) => (
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
            <button
              type="submit"
              style={{
                padding: '10px',
                background: '#2563eb',
                color: '#fff',
                border: 'none',
                borderRadius: '6px',
                cursor: 'pointer',
                fontWeight: 600,
              }}
            >
              Tạo người dùng (Sinh mật khẩu tạm)
            </button>
          </div>
        </form>

        <form
          onSubmit={handleCreateGroup}
          style={{ border: '1px solid #e2e8f0', borderRadius: '10px', padding: '16px', background: '#fff' }}
        >
          <h3 style={{ marginTop: 0, fontWeight: 600, marginBottom: '12px' }}>Tạo Phòng ban / Nhóm quyền</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <input
              type="text"
              placeholder="Tên phòng ban (vd: Tài chính, Pháp chế)"
              value={groupName}
              onChange={(e) => setGroupName(e.target.value)}
              required
              style={{ padding: '8px', borderRadius: '6px', border: '1px solid #cbd5e1' }}
            />
            <input
              type="text"
              placeholder="Mô tả chức năng (tùy chọn)"
              value={groupDescription}
              onChange={(e) => setGroupDescription(e.target.value)}
              style={{ padding: '8px', borderRadius: '6px', border: '1px solid #cbd5e1' }}
            />
            <button
              type="submit"
              style={{
                padding: '10px',
                background: '#0f172a',
                color: '#fff',
                border: 'none',
                borderRadius: '6px',
                cursor: 'pointer',
                fontWeight: 600,
              }}
            >
              Thêm phòng ban
            </button>
          </div>

          <h4 style={{ marginBottom: '8px', marginTop: '20px', fontWeight: 600 }}>Danh sách Phòng ban</h4>
          <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {groups.map((g) => (
              <li
                key={g.id}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '8px 0',
                  borderBottom: '1px solid #f1f5f9',
                  fontSize: '13px',
                }}
              >
                <span>
                  <strong>{g.name}</strong>
                  {g.deleted_at && <span style={{ color: '#dc2626', marginLeft: '6px' }}>[Đã xóa mềm]</span>}
                </span>
                {!g.deleted_at && (
                  <button
                    type="button"
                    onClick={() => void handleDeleteGroup(g.id, g.name)}
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
                    Xóa mềm
                  </button>
                )}
              </li>
            ))}
          </ul>
        </form>
      </div>

      <h3 style={{ fontWeight: 600, marginBottom: '10px' }}>Danh sách Tài khoản Nhân viên</h3>
      <table style={{ width: '100%', borderCollapse: 'collapse', background: '#fff', fontSize: '14px' }}>
        <thead>
          <tr style={{ background: '#f8fafc', textAlign: 'left', borderBottom: '2px solid #e2e8f0' }}>
            <th style={{ padding: '10px' }}>Username</th>
            <th style={{ padding: '10px' }}>Họ tên</th>
            <th style={{ padding: '10px' }}>Vai trò</th>
            <th style={{ padding: '10px' }}>Phòng ban</th>
            <th style={{ padding: '10px' }}>Trạng thái</th>
            <th style={{ padding: '10px' }}>Thao tác</th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} style={{ borderBottom: '1px solid #e2e8f0' }}>
              <td style={{ padding: '10px', fontWeight: 600 }}>{u.username}</td>
              <td style={{ padding: '10px' }}>{u.display_name}</td>
              <td style={{ padding: '10px' }}>{u.roles.join(', ')}</td>
              <td style={{ padding: '10px' }}>
                {u.groups.map((g) => g.name).join(', ') || <em style={{ color: '#94a3b8' }}>Toàn công ty</em>}
              </td>
              <td style={{ padding: '10px' }}>
                <span
                  style={{
                    padding: '2px 8px',
                    borderRadius: '999px',
                    fontSize: '12px',
                    background: u.status === 'active' ? '#dcfce7' : '#fee2e2',
                    color: u.status === 'active' ? '#166534' : '#991b1b',
                  }}
                >
                  {u.status}
                </span>
              </td>
              <td style={{ padding: '10px', display: 'flex', gap: '8px' }}>
                <button
                  type="button"
                  onClick={() => void handleToggleUserStatus(u)}
                  style={{
                    padding: '4px 10px',
                    borderRadius: '6px',
                    border: '1px solid #cbd5e1',
                    background: '#f8fafc',
                    cursor: 'pointer',
                    fontSize: '12px',
                  }}
                >
                  {u.status === 'active' ? 'Vô hiệu hóa' : 'Kích hoạt'}
                </button>
                <button
                  type="button"
                  onClick={() => void handleResetPassword(u)}
                  style={{
                    padding: '4px 10px',
                    borderRadius: '6px',
                    border: '1px solid #bfdbfe',
                    background: '#eff6ff',
                    color: '#1d4ed8',
                    cursor: 'pointer',
                    fontSize: '12px',
                  }}
                >
                  Đặt lại MK
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};
