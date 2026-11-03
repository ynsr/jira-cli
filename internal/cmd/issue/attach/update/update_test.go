package update

import (
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/spf13/pflag"
	"github.com/stretchr/testify/assert"

	"github.com/ankitpokhrel/jira-cli/pkg/jira"
)

func testFlags(byName bool) *pflag.FlagSet {
	flags := pflag.NewFlagSet("test", pflag.ContinueOnError)
	flags.Bool("by-name", byName, "")
	flags.Bool("debug", false, "")
	return flags
}

func TestParseIDMode(t *testing.T) {
	params := parseArgsAndFlags(testFlags(false), []string{"ISSUE-1", "10000", "./a.txt"}, "")
	assert.Equal(t, "ISSUE-1", params.key)
	assert.Equal(t, "10000", params.id)
	assert.Equal(t, []string{"./a.txt"}, params.files)
	assert.False(t, params.byName)
}

func TestParseByNameMode(t *testing.T) {
	params := parseArgsAndFlags(testFlags(true), []string{"ISSUE-1", "./a.txt"}, "")
	assert.Equal(t, "ISSUE-1", params.key)
	assert.Empty(t, params.id)
	assert.Equal(t, []string{"./a.txt"}, params.files)
	assert.True(t, params.byName)
}

func TestParseEmptyArgs(t *testing.T) {
	params := parseArgsAndFlags(testFlags(false), []string{}, "")
	assert.Empty(t, params.key)
	assert.Empty(t, params.id)
	assert.Empty(t, params.files)
}

func TestValidateRequiresKey(t *testing.T) {
	uc := updateCmd{params: &updateParams{id: "10000", files: []string{"a.txt"}}}
	assert.Error(t, uc.validate())
}

func TestValidateRequiresIDWithoutByName(t *testing.T) {
	uc := updateCmd{params: &updateParams{key: "ISSUE-1", files: []string{"a.txt"}}}
	assert.Error(t, uc.validate())
}

func TestValidateFilesRejectsDirectory(t *testing.T) {
	uc := updateCmd{params: &updateParams{key: "ISSUE-1", id: "10000", files: []string{t.TempDir()}}}
	assert.Error(t, uc.validateFiles())
	assert.Contains(t, uc.validateFiles().Error(), "directory")
}

func TestValidateIDModeRequiresSingleFile(t *testing.T) {
	uc := updateCmd{params: &updateParams{key: "ISSUE-1", id: "10000"}}
	assert.Error(t, uc.validate())

	uc = updateCmd{params: &updateParams{key: "ISSUE-1", id: "10000", files: []string{"a.txt", "b.txt"}}}
	assert.Error(t, uc.validate())
}

func TestValidateByNameRejectsMultipleFiles(t *testing.T) {
	uc := updateCmd{params: &updateParams{key: "ISSUE-1", byName: true, files: []string{"a.txt", "b.txt"}}}
	assert.Error(t, uc.validate())
}

func TestValidateByNameRequiresFile(t *testing.T) {
	uc := updateCmd{params: &updateParams{key: "ISSUE-1", byName: true}}
	assert.Error(t, uc.validate())
}

func TestFindAttachmentIDByName(t *testing.T) {
	attachments := []jira.Attachment{{ID: "10000", Filename: "a.txt"}, {ID: "10001", Filename: "b.txt"}}
	id, err := findAttachmentIDByName(attachments, "a.txt", "TEST-1")
	assert.NoError(t, err)
	assert.Equal(t, "10000", id)

	_, err = findAttachmentIDByName(attachments, "missing.txt", "TEST-1")
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "no attachment found")
}

func TestRunIDModeDeletesThenUploads(t *testing.T) {
	dir := t.TempDir()
	filePath := filepath.Join(dir, "a.txt")
	assert.NoError(t, os.WriteFile(filePath, []byte("new content"), 0o600))

	var deleted, uploaded bool
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.Method == http.MethodDelete && r.URL.Path == "/rest/api/2/attachment/10000":
			deleted = true
			w.WriteHeader(204)
		case r.Method == http.MethodPost && r.URL.Path == "/rest/api/2/issue/TEST-1/attachments":
			uploaded = true
			assert.True(t, deleted, "delete must happen before upload")
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(200)
			_, _ = w.Write([]byte(`[{"id":"10001","filename":"a.txt","size":11,"mimeType":"text/plain","content":"http://x/attachment/10001","author":{"displayName":"Ada","emailAddress":"a@x.io","active":true},"created":"2024-01-01T00:00:00.000+0000"}]`))
		default:
			w.WriteHeader(404)
		}
	}))
	defer server.Close()

	client := jira.NewClient(jira.Config{Server: server.URL}, jira.WithTimeout(3*time.Second))
	uc := updateCmd{client: client, params: &updateParams{key: "TEST-1", id: "10000", files: []string{filePath}}}
	assert.NoError(t, uc.run())
	assert.True(t, deleted)
	assert.True(t, uploaded)
}

func TestRunByNameModeResolvesIDFromListing(t *testing.T) {
	dir := t.TempDir()
	filePath := filepath.Join(dir, "a.txt")
	assert.NoError(t, os.WriteFile(filePath, []byte("new content"), 0o600))

	var deletedID string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/rest/api/2/issue/TEST-1":
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(200)
			_, _ = w.Write([]byte(`{"key":"TEST-1","fields":{"attachment":[{"id":"10000","filename":"a.txt","size":1,"mimeType":"text/plain","content":"http://x/1","author":{"displayName":"Ada","emailAddress":"a@x.io","active":true},"created":"2024-01-01T00:00:00.000+0000"}]}}`))
		case "/rest/api/2/attachment/10000":
			assert.Equal(t, http.MethodDelete, r.Method)
			deletedID = "10000"
			w.WriteHeader(204)
		case "/rest/api/2/issue/TEST-1/attachments":
			assert.Equal(t, http.MethodPost, r.Method)
			assert.Equal(t, "10000", deletedID)
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(200)
			_, _ = w.Write([]byte(`[{"id":"10001","filename":"a.txt","size":11,"mimeType":"text/plain","content":"http://x/attachment/10001","author":{"displayName":"Ada","emailAddress":"a@x.io","active":true},"created":"2024-01-01T00:00:00.000+0000"}]`))
		default:
			w.WriteHeader(404)
		}
	}))
	defer server.Close()

	client := jira.NewClient(jira.Config{Server: server.URL}, jira.WithTimeout(3*time.Second))
	uc := updateCmd{client: client, params: &updateParams{key: "TEST-1", byName: true, files: []string{filePath}}}
	assert.NoError(t, uc.run())
	assert.Equal(t, "10000", deletedID)
}

func TestRunByNameNoMatch(t *testing.T) {
	dir := t.TempDir()
	filePath := filepath.Join(dir, "missing.txt")
	assert.NoError(t, os.WriteFile(filePath, []byte("x"), 0o600))

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(200)
		_, _ = w.Write([]byte(`{"key":"TEST-1","fields":{"attachment":[]}}`))
	}))
	defer server.Close()

	client := jira.NewClient(jira.Config{Server: server.URL}, jira.WithTimeout(3*time.Second))
	uc := updateCmd{client: client, params: &updateParams{key: "TEST-1", byName: true, files: []string{filePath}}}
	err := uc.run()
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "no attachment found")
}
