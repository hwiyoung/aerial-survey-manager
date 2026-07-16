/**
 * Authentication Context and Provider
 */
import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import api from '../api/client';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    // Check for existing session on mount
    useEffect(() => {
        const checkAuth = async () => {
            const token = localStorage.getItem('access_token');
            if (token) {
                try {
                    const userData = await api.getCurrentUser();
                    setUser(userData);
                } catch {
                    // Token expired or invalid
                    localStorage.removeItem('access_token');
                    localStorage.removeItem('refresh_token');
                }
            }
            setLoading(false);
        };
        checkAuth();
    }, []);

    const login = useCallback(async (email, password) => {
        setError(null);
        try {
            await api.login(email, password);
            const userData = await api.getCurrentUser();
            setUser(userData);
            return true;
        } catch (err) {
            setError(err?.response?.data?.detail || err.message || '로그인에 실패했습니다.');
            return false;
        }
    }, []);

    const logout = useCallback(async () => {
        try {
            await api.logout();
        } catch {
            // Ignore errors
        }
        setUser(null);
    }, []);

    const clearAuthState = useCallback(() => {
        setUser(null);
        setError(null);
    }, []);

    const value = {
        user,
        loading,
        error,
        organizationId: user?.organization_id || null,
        isAuthenticated: !!user,
        canCreateProject: !!user,
        canEditProject: !!user,
        canDeleteProject: !!user,
        login,
        logout,
        clearAuthState,
        clearError: () => setError(null),
    };

    return (
        <AuthContext.Provider value={value}>
            {children}
        </AuthContext.Provider>
    );
}

export function useAuth() {
    const context = useContext(AuthContext);
    if (!context) {
        throw new Error('useAuth must be used within AuthProvider');
    }
    return context;
}

export default AuthContext;
