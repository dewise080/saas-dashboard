import { useState } from 'react';
import { useFlowStore } from '../store';
import type { N8nWorkflow } from '../types';

interface ToolbarProps {
  onImport: () => void;
  onExport: () => void;
}

export const Toolbar = ({ onImport, onExport }: ToolbarProps) => {
  const { workflowName, setWorkflowName, isDirty, clearWorkflow, nodes, layoutFlow } = useFlowStore();
  const [isEditing, setIsEditing] = useState(false);
  const [localName, setLocalName] = useState(workflowName);

  const handleNameSubmit = () => {
    setWorkflowName(localName);
    setIsEditing(false);
  };

  return (
    <div className="bg-n8n-gray border-b border-gray-700 px-4 py-3 flex items-center justify-between">
      {/* Left side - Workflow name */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          {isEditing ? (
            <input
              type="text"
              value={localName}
              onChange={(e) => setLocalName(e.target.value)}
              onBlur={handleNameSubmit}
              onKeyDown={(e) => e.key === 'Enter' && handleNameSubmit()}
              className="bg-n8n-dark border border-gray-600 rounded px-2 py-1 text-white focus:border-blue-500 focus:outline-none"
              autoFocus
            />
          ) : (
            <h1
              className="text-lg font-semibold text-white cursor-pointer hover:text-blue-400 transition-colors"
              onClick={() => {
                setLocalName(workflowName);
                setIsEditing(true);
              }}
            >
              {workflowName}
            </h1>
          )}
          {isDirty && (
            <span className="text-xs text-orange-400">• Unsaved</span>
          )}
        </div>
        
        <div className="text-sm text-gray-400">
          {nodes.length} node{nodes.length !== 1 ? 's' : ''}
        </div>
      </div>

      {/* Right side - Actions */}
      <div className="flex items-center gap-2">
        <button
          onClick={onImport}
          className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded transition-colors flex items-center gap-1"
        >
          📥 Import JSON
        </button>
        
        <button
          onClick={onExport}
          className="px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white text-sm rounded transition-colors flex items-center gap-1"
        >
          📤 Export JSON
        </button>

        <button
          onClick={() => layoutFlow('LR')}
          disabled={!nodes.length}
          className="px-3 py-1.5 bg-purple-600 hover:bg-purple-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white text-sm rounded transition-colors flex items-center gap-1"
        >
          🧭 Auto Layout
        </button>
        
        <button
          onClick={() => {
            if (confirm('Clear the entire workflow?')) {
              clearWorkflow();
            }
          }}
          className="px-3 py-1.5 bg-gray-600 hover:bg-gray-700 text-white text-sm rounded transition-colors"
        >
          🗑️ Clear
        </button>
      </div>
    </div>
  );
};

// Import Modal Component
interface ImportModalProps {
  isOpen: boolean;
  onClose: () => void;
  onImport: (workflow: N8nWorkflow) => void;
}

export const ImportModal = ({ isOpen, onClose, onImport }: ImportModalProps) => {
  const [jsonInput, setJsonInput] = useState('');
  const [error, setError] = useState('');

  if (!isOpen) return null;

  const handleImport = () => {
    try {
      const workflow = JSON.parse(jsonInput) as N8nWorkflow;
      
      // Basic validation
      if (!workflow.nodes || !Array.isArray(workflow.nodes)) {
        throw new Error('Invalid workflow: missing nodes array');
      }
      
      onImport(workflow);
      setJsonInput('');
      setError('');
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Invalid JSON');
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-n8n-gray rounded-lg shadow-xl w-full max-w-2xl mx-4">
        <div className="p-4 border-b border-gray-700 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Import n8n Workflow JSON</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white transition-colors"
          >
            ✕
          </button>
        </div>
        
        <div className="p-4">
          <textarea
            value={jsonInput}
            onChange={(e) => {
              setJsonInput(e.target.value);
              setError('');
            }}
            placeholder='Paste your n8n workflow JSON here...\n\n{"name": "My Workflow", "nodes": [...], "connections": {...}}'
            className="w-full h-80 bg-n8n-dark border border-gray-600 rounded p-3 text-white font-mono text-sm resize-none focus:border-blue-500 focus:outline-none"
          />
          
          {error && (
            <div className="mt-2 text-red-400 text-sm">
              ❌ {error}
            </div>
          )}
        </div>
        
        <div className="p-4 border-t border-gray-700 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-gray-600 hover:bg-gray-700 text-white rounded transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleImport}
            disabled={!jsonInput.trim()}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded transition-colors"
          >
            Import
          </button>
        </div>
      </div>
    </div>
  );
};

// Export Modal Component
interface ExportModalProps {
  isOpen: boolean;
  onClose: () => void;
  workflow: N8nWorkflow | null;
}

export const ExportModal = ({ isOpen, onClose, workflow }: ExportModalProps) => {
  if (!isOpen || !workflow) return null;

  const jsonString = JSON.stringify(workflow, null, 2);

  const handleCopy = () => {
    navigator.clipboard.writeText(jsonString);
    alert('Copied to clipboard!');
  };

  const handleDownload = () => {
    const blob = new Blob([jsonString], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${workflow.name.replace(/\s+/g, '_')}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-n8n-gray rounded-lg shadow-xl w-full max-w-2xl mx-4">
        <div className="p-4 border-b border-gray-700 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Export Workflow JSON</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white transition-colors"
          >
            ✕
          </button>
        </div>
        
        <div className="p-4">
          <textarea
            value={jsonString}
            readOnly
            className="w-full h-80 bg-n8n-dark border border-gray-600 rounded p-3 text-white font-mono text-sm resize-none"
          />
        </div>
        
        <div className="p-4 border-t border-gray-700 flex justify-end gap-2">
          <button
            onClick={handleCopy}
            className="px-4 py-2 bg-gray-600 hover:bg-gray-700 text-white rounded transition-colors"
          >
            📋 Copy
          </button>
          <button
            onClick={handleDownload}
            className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded transition-colors"
          >
            💾 Download
          </button>
          <button
            onClick={onClose}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
