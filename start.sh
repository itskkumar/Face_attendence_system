#!/bin/bash
# Quick Start Script for Face Attendance System with New UI

echo "🎓 Face Attendance System - Quick Start"
echo "========================================"
echo ""

# Check if streamlit is installed
if ! command -v streamlit &> /dev/null
then
    echo "⚠️  Streamlit not found. Installing..."
    pip install streamlit streamlit-autorefresh
fi

echo "✅ Starting the application..."
echo ""
echo "📌 Default Credentials:"
echo "   Admin Login:"
echo "   - Username: admin"
echo "   - Password: admin123"
echo ""
echo "   Student Login:"
echo "   - Username: <your_roll_number>"
echo "   - Password: student123"
echo ""
echo "🌐 Opening browser..."
echo ""

# Start streamlit
streamlit run dashboard.py
