/**
 * Authentication Context and Provider
 */
import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import api from '../api/client';

const AuthContext = createContext(null);

const ROLE_ORDER = ['viewer', 'editor', 'admin'];
const ROLE_ALIASES = {
    viewer: 'viewer',
    editor: 'editor',
    admin: 'admin',
    user: 'viewer',
    manager: 'editor',
};

const normalizeRole = (role) => {
    if (!role || typeof role !== 'string') return 'viewer';
    const mappedRole = ROLE_ALIASES[role.toLowerCase().trim()] || 'user';
    return ROLE_ORDER.includes(mappedRole) ? mappedRole : 'viewer';
};

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
                } catch (err) {
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
            setError(err.message);
            return false;
        }
    }, []);

    const register = useCallback(async (email, password, name) => {
        setError(null);
        try {
            await api.register(email, password, name);
            // Auto-login after registration
            return await login(email, password);
        } catch (err) {
            setError(err.message);
            return false;
        }
    }, [login]);

    const currentRole = normalizeRole(user?.role);

    const hasRole = useCallback((requiredRole) => {
        if (typeof requiredRole !== 'string') return false;
        const normalizedRequiredRole =
            ROLE_ALIASES[requiredRole.toLowerCase().trim()] || 'viewer';
        if (!ROLE_ORDER.includes(normalizedRequiredRole)) return false;
        const currentRank = ROLE_ORDER.indexOf(currentRole);
        const targetRank = ROLE_ORDER.indexOf(normalizedRequiredRole);
        return currentRank >= targetRank;
    }, [currentRole]);

    const logout = useCallback(async () => {
        try {
            await api.logout();
        } catch (err) {
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
        role: currentRole,
        organizationId: user?.organization_id || null,
        isAuthenticated: !!user,
        isAdmin: currentRole === 'admin',
        isManager: currentRole === 'admin' || currentRole === 'editor',
        canCreateProject: hasRole('editor'),
        canEditProject: hasRole('editor'),
        canDeleteProject: hasRole('editor'),
        canManageUsers: currentRole === 'admin',
        canManageOrganizations: currentRole === 'admin',
        canManagePermissions: currentRole === 'admin',
        hasRole,
        login,
        register,
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
