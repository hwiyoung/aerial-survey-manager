/**
 * Authentication Context and Provider
 */
import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
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

    const logout = useCallback(async () => {
        try {
            await api.logout();
        } catch (err) {
            // Ignore errors
        }
        setUser(null);
    }, []);

    const value = {
        user,
        loading,
        error,
        isAuthenticated: !!user,
        login,
        register,
        logout,
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
