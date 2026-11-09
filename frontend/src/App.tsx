import React, { useEffect, useState } from 'react';
import { getMe, logout, UserProfile } from './services/api';
import { LoginPage } from './pages/LoginPage';
import { ChatPage } from './pages/ChatPage';
import { AdminDocumentsPage } from './pages/AdminDocumentsPage';
import { AdminUsersPage } from './pages/AdminUsersPage';
import { OpsPage } from './pages/OpsPage';

type ActiveTab = 'chat' | 'admin_docs' | 'admin_users' | 'ops';

export const App: React.FC = () => {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [tab, setTab] = useState<ActiveTab>('chat');

  useEffect(() => {
    getMe()
      .then((profile) => setUser(profile))
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div style={{ padding: '48px', textAlign: 'center', fontFamily: 'system-ui, sans-serif' }}>
        Đang khởi tạo phiên làm việc...
      </div>
    );
  }

  if (!user || user.must_change_password) {
    return <LoginPage existingUser={user} onAuthenticated={(u) => setUser(u)} />;
  }

  const isAdmin = user.roles.includes('admin');
  const isContentAdmin = user.roles.includes('content_admin') || isAdmin;
  const isOps = user.roles.includes('operator') || user.roles.includes('ops') || isAdmin;

  const handleLogout = async () => {
    await logout();
    setUser(null);
    setTab('chat');
  };

  return (
    <div style={{ minHeight: '100vh', background: '#f8fafc', fontFamily: 'system-ui, sans-serif' }}>
      <header
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '12px 24px',
          background: '#0f172a',
          color: '#fff',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
          <strong style={{ fontSize: '16px' }}>Trợ lý Tri thức Nội bộ Song ngữ (VI/EN)</strong>
          <nav style={{ display: 'flex', gap: '8px' }}>
            <button
              type="button"
              onClick={() => setTab('chat')}
              style={{
                padding: '6px 12px',
                borderRadius: '6px',
                border: 'none',
                background: tab === 'chat' ? '#2563eb' : 'transparent',
                color: '#fff',
                cursor: 'pointer',
              }}
            >
              Hỏi đáp Tài liệu
            </button>
            {isContentAdmin && (
              <button
                type="button"
                onClick={() => setTab('admin_docs')}
                style={{
                  padding: '6px 12px',
                  borderRadius: '6px',
                  border: 'none',
                  background: tab === 'admin_docs' ? '#2563eb' : 'transparent',
                  color: '#fff',
                  cursor: 'pointer',
                }}
              >
                Quản trị Tài liệu
              </button>
            )}
            {isAdmin && (
              <button
                type="button"
                onClick={() => setTab('admin_users')}
                style={{
                  padding: '6px 12px',
                  borderRadius: '6px',
                  border: 'none',
                  background: tab === 'admin_users' ? '#2563eb' : 'transparent',
                  color: '#fff',
                  cursor: 'pointer',
                }}
              >
                Người dùng & Phòng ban
              </button>
            )}
            {isOps && (
              <button
                type="button"
                onClick={() => setTab('ops')}
                style={{
                  padding: '6px 12px',
                  borderRadius: '6px',
                  border: 'none',
                  background: tab === 'ops' ? '#2563eb' : 'transparent',
                  color: '#fff',
                  cursor: 'pointer',
                }}
              >
                Vận hành (Ops)
              </button>
            )}
          </nav>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', fontSize: '13px' }}>
          <span>
            {user.display_name} ({user.groups.map((g) => g.name).join(', ') || 'Toàn công ty'})
          </span>
          <button
            type="button"
            onClick={handleLogout}
            style={{
              padding: '6px 10px',
              borderRadius: '6px',
              border: '1px solid #475569',
              background: 'transparent',
              color: '#f8fafc',
              cursor: 'pointer',
            }}
          >
            Đăng xuất
          </button>
        </div>
      </header>

      <main>
        {tab === 'chat' && <ChatPage />}
        {tab === 'admin_docs' && isContentAdmin && <AdminDocumentsPage />}
        {tab === 'admin_users' && isAdmin && <AdminUsersPage />}
        {tab === 'ops' && isOps && <OpsPage />}
      </main>
    </div>
  );
};

export default App;
