import { useState, useEffect } from 'react';
import { useFlowStore } from '../store';
import type { Credential } from '../types';

// Django API base URL - adjust based on environment
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export const NodeInspector = () => {
  const { selectedNode, updateNode, removeNode, setSelectedNode } = useFlowStore();
  const [localName, setLocalName] = useState('');
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (selectedNode) {
      setLocalName(selectedNode.data.label);
      fetchCredentialsForNode(selectedNode.data.type);
    }
  }, [selectedNode]);

  const fetchCredentialsForNode = async (nodeType: string) => {
    // Determine required credential type based on node type
    let credType = '';
    if (nodeType.toLowerCase().includes('openai') || nodeType.toLowerCase().includes('langchain')) {
      credType = 'openAiApi';
    } else if (nodeType.toLowerCase().includes('evolution') || nodeType.toLowerCase().includes('whatsapp')) {
      credType = 'evolutionApi';
    } else if (nodeType.toLowerCase().includes('postgres')) {
      credType = 'postgresDb';
    }

    if (!credType) {
      setCredentials([]);
      return;
    }

    setLoading(true);
    try {
      const response = await fetch(`${API_BASE_URL}/api/n8n/credentials/?type=${credType}`, {
        credentials: 'include',  // Include cookies for Django session auth
      });
      const data = await response.json();
      setCredentials(data.credentials || []);
    } catch (error) {
      console.error('Failed to fetch credentials:', error);
      setCredentials([]);
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => {
    setSelectedNode(null);
  };

  if (!selectedNode) {
    return (
      <div className="w-80 bg-n8n-gray border-l border-gray-700 p-4">
        <div className="text-gray-400 text-center py-8">
          <p className="text-2xl mb-2">👆</p>
          <p>Select a node to inspect</p>
        </div>
      </div>
    );
  }

  const handleNameChange = () => {
    if (localName !== selectedNode.data.label) {
      updateNode(selectedNode.id, { label: localName });
    }
  };

  const handleCredentialChange = (credType: string, credId: string, credName: string) => {
    const newCredentials = {
      ...selectedNode.data.credentials,
      [credType]: { id: credId, name: credName },
    };
    updateNode(selectedNode.id, { credentials: newCredentials });
  };

  const handleDelete = () => {
    if (confirm('Delete this node?')) {
      removeNode(selectedNode.id);
    }
  };

  return (
    <div className="w-80 bg-n8n-gray border-l border-gray-700 flex flex-col h-full">
      {/* Header */}
      <div className="p-4 border-b border-gray-700 flex items-center justify-between">
        <h3 className="font-semibold text-white">Node Inspector</h3>
        <button
          onClick={handleClose}
          className="text-gray-400 hover:text-white transition-colors"
        >
          ✕
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Node Name */}
        <div>
          <label className="block text-sm text-gray-400 mb-1">Name</label>
          <input
            type="text"
            value={localName}
            onChange={(e) => setLocalName(e.target.value)}
            onBlur={handleNameChange}
            className="w-full bg-n8n-dark border border-gray-600 rounded px-3 py-2 text-white focus:border-blue-500 focus:outline-none"
          />
        </div>

        {/* Node Type */}
        <div>
          <label className="block text-sm text-gray-400 mb-1">Type</label>
          <div className="bg-n8n-dark border border-gray-600 rounded px-3 py-2 text-gray-300 text-sm">
            {selectedNode.data.type}
          </div>
        </div>

        {/* Credentials Section */}
        {loading ? (
          <div>
            <label className="block text-sm text-gray-400 mb-1">
              🔑 Credentials
            </label>
            <div className="bg-n8n-dark border border-gray-600 rounded px-3 py-2 text-gray-500 text-sm">
              Loading credentials...
            </div>
          </div>
        ) : credentials.length > 0 ? (
          <div>
            <label className="block text-sm text-gray-400 mb-1">
              🔑 Credentials
            </label>
            <select
              className="w-full bg-n8n-dark border border-gray-600 rounded px-3 py-2 text-white focus:border-blue-500 focus:outline-none"
              value={
                selectedNode.data.credentials?.[credentials[0]?.type]?.id || ''
              }
              onChange={(e) => {
                const cred = credentials.find((c) => c.id === e.target.value);
                if (cred) {
                  handleCredentialChange(cred.type, cred.id, cred.name);
                }
              }}
            >
              <option value="">Select credential...</option>
              {credentials.map((cred) => (
                <option key={cred.id} value={cred.id}>
                  {cred.name}
                </option>
              ))}
            </select>
          </div>
        ) : null}

        {/* Parameters Preview */}
        <div>
          <label className="block text-sm text-gray-400 mb-1">Parameters</label>
          <div className="bg-n8n-dark border border-gray-600 rounded p-3 max-h-48 overflow-y-auto">
            <pre className="text-xs text-gray-300 whitespace-pre-wrap">
              {JSON.stringify(selectedNode.data.parameters, null, 2)}
            </pre>
          </div>
        </div>

        {/* Node ID */}
        <div>
          <label className="block text-sm text-gray-400 mb-1">Node ID</label>
          <div className="bg-n8n-dark border border-gray-600 rounded px-3 py-2 text-gray-500 text-xs font-mono">
            {selectedNode.id}
          </div>
        </div>
      </div>

      {/* Footer Actions */}
      <div className="p-4 border-t border-gray-700 space-y-2">
        <button
          onClick={handleDelete}
          className="w-full bg-red-600 hover:bg-red-700 text-white py-2 px-4 rounded transition-colors"
        >
          🗑️ Delete Node
        </button>
      </div>
    </div>
  );
};
