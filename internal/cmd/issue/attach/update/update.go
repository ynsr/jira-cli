package update

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/spf13/cobra"
	"github.com/spf13/viper"

	"github.com/ankitpokhrel/jira-cli/api"
	"github.com/ankitpokhrel/jira-cli/internal/cmdutil"
	"github.com/ankitpokhrel/jira-cli/internal/query"
	"github.com/ankitpokhrel/jira-cli/pkg/jira"
)

const (
	helpText = `Update replaces an existing attachment by deleting it and uploading a new file with the same name. Jira has no in-place attachment update, so the replacement gets a new attachment ID. The upload happens after the delete; if the upload fails, the old attachment is already gone.`
	examples = `$ jira issue attach update ISSUE-1 10000 ./screenshot.png

# Match the existing attachment by file name instead of ID
$ jira issue attach update ISSUE-1 ./screenshot.png --by-name`
)

// NewCmdUpdate is an attachment update command.
func NewCmdUpdate() *cobra.Command {
	cmd := &cobra.Command{
		Use:     "update ISSUE-KEY [ATTACHMENT-ID] FILE [--by-name]",
		Short:   "Update an attachment by replacing its file",
		Long:    helpText,
		Example: examples,
		Aliases: []string{"replace"},
		Annotations: map[string]string{
			"help:args": `ISSUE-KEY	Issue key, eg: ISSUE-1
ATTACHMENT-ID	ID of the attachment to replace (omit with --by-name)
FILE	Path to the replacement file`,
		},
		Run: update,
	}

	cmd.Flags().Bool("by-name", false, "Match the existing attachment by file name instead of ID")

	return cmd
}

func update(cmd *cobra.Command, args []string) {
	project := viper.GetString("project.key")
	params := parseArgsAndFlags(cmd.Flags(), args, project)
	client := api.DefaultClient(params.debug)
	ac := updateCmd{client: client, params: params}

	cmdutil.ExitIfError(ac.setIssueKey(project))
	cmdutil.ExitIfError(ac.validate())
	cmdutil.ExitIfError(ac.validateFiles())

	err := func() error {
		s := cmdutil.Info(fmt.Sprintf("Updating attachment for issue %q", ac.params.key))
		defer s.Stop()

		return ac.run()
	}()
	cmdutil.ExitIfError(err)

	cmdutil.Success(fmt.Sprintf("Updated attachment for issue %q", ac.params.key))
}

type updateParams struct {
	key    string
	id     string
	files  []string
	byName bool
	debug  bool
}

func parseArgsAndFlags(flags query.FlagParser, args []string, project string) *updateParams {
	var key, id string
	var files []string
	var rest []string

	if len(args) >= 1 {
		key = cmdutil.GetJiraIssueKey(project, args[0])
		rest = args[1:]
	}
	byName, err := flags.GetBool("by-name")
	cmdutil.ExitIfError(err)

	if byName {
		files = rest
	} else {
		if len(rest) >= 1 {
			id = rest[0]
		}
		if len(rest) >= 2 {
			files = rest[1:]
		}
	}

	debug, err := flags.GetBool("debug")
	cmdutil.ExitIfError(err)

	return &updateParams{key: key, id: id, files: files, byName: byName, debug: debug}
}

type updateCmd struct {
	client *jira.Client
	params *updateParams
}

func (uc *updateCmd) setIssueKey(project string) error {
	if uc.params.key != "" {
		return nil
	}
	return fmt.Errorf("issue key is required: jira issue attach update ISSUE-KEY [ATTACHMENT-ID] FILE [--by-name]")
}

func (uc *updateCmd) validate() error {
	if uc.params.key == "" {
		return fmt.Errorf("issue key is required: jira issue attach update ISSUE-KEY [ATTACHMENT-ID] FILE [--by-name]")
	}
	if uc.params.byName {
		if len(uc.params.files) != 1 {
			return fmt.Errorf("exactly one replacement file is required: jira issue attach update ISSUE-KEY FILE [--by-name]")
		}
		return nil
	}
	if uc.params.id == "" {
		return fmt.Errorf("attachment id is required (or use --by-name): jira issue attach update ISSUE-KEY ATTACHMENT-ID FILE [--by-name]")
	}
	if len(uc.params.files) != 1 {
		return fmt.Errorf("exactly one replacement file is required: jira issue attach update ISSUE-KEY ATTACHMENT-ID FILE [--by-name]")
	}
	return nil
}

func (uc *updateCmd) validateFiles() error {
	for _, f := range uc.params.files {
		info, err := os.Stat(f)
		if err != nil {
			return fmt.Errorf("cannot access file %q: %w", f, err)
		}
		if info.IsDir() {
			return fmt.Errorf("cannot attach directory %q: provide a file", f)
		}
	}
	return nil
}

func (uc *updateCmd) run() error {
	if err := uc.validate(); err != nil {
		return err
	}
	id := uc.params.id
	if uc.params.byName {
		attachments, err := uc.client.ListAttachments(uc.params.key)
		if err != nil {
			return err
		}
		resolved, err := findAttachmentIDByName(attachments, filepath.Base(uc.params.files[0]), uc.params.key)
		if err != nil {
			return err
		}
		id = resolved
	}
	if err := uc.client.DeleteAttachment(id); err != nil {
		return err
	}
	uploaded, err := uc.client.UploadAttachment(uc.params.key, uc.params.files)
	if err != nil {
		return fmt.Errorf("deleted attachment %s but upload failed: %w", id, err)
	}
	for _, a := range uploaded {
		fmt.Printf("  %s  id=%s  %d bytes\n", a.Filename, a.ID, a.Size)
	}
	return nil
}

func findAttachmentIDByName(attachments []jira.Attachment, name, key string) (string, error) {
	for _, a := range attachments {
		if a.Filename == name {
			return a.ID, nil
		}
	}
	return "", fmt.Errorf("no attachment found with filename %q for issue %q", name, key)
}
