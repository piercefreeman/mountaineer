package main

import (
	"C"
	"fmt"
	"sync"
)
import (
	"os"

	"github.com/evanw/esbuild/pkg/api"
)

var (
	mutex    sync.Mutex
	contexts = make(map[int]*ESBuildContext)
	nextID   = 1
)

type ESBuildContext struct {
	Filename string
	Context  api.BuildContext
}

//export GetBuildContext
func GetBuildContext(
	rawFilename *C.char,
	isSSR C.int,
) C.int {
	mutex.Lock()
	defer mutex.Unlock()

	filename := C.GoString(rawFilename)

	// If we already have the filename registered, return
	// the existing context ID.
	for id, context := range contexts {
		if context.Filename == filename {
			return C.int(id)
		}
	}

	buildOptions := api.BuildOptions{
		EntryPoints: []string{filename},
		Bundle:      true,
		Outfile:     filename + ".out",
		Sourcemap:   api.SourceMapExternal,
		Define: map[string]string{
			"process.env.NODE_ENV":      "\"production\"",
			"process.env.SSR_RENDERING": "false",
		},
		Loader: map[string]api.Loader{
			".tsx": api.LoaderTSX,
			".jsx": api.LoaderJSX,
		},
		// NodePaths: []string{"node_modules"},
	}

	if isSSR == 1 {
		buildOptions.GlobalName = "SSR"
		buildOptions.Format = api.FormatIIFE
	} else {
		buildOptions.Format = api.FormatESModule
	}

	ctx, err := api.Context(buildOptions)
	fmt.Printf("Writing output: filename: %s, outfile: %s\n", filename, filename+".out")
	if err != nil {
		// Log the error
		fmt.Println(err)
		os.Exit(1)
	}

	id := nextID
	nextID++
	contexts[id] = &ESBuildContext{
		Filename: filename,
		Context:  ctx,
	}
	return C.int(id)
}

//export RebuildContext
func RebuildContext(id C.int) {
	mutex.Lock()
	defer mutex.Unlock()

	context, exists := contexts[int(id)]
	if !exists {
		fmt.Printf("Context with ID %d does not exist\n", id)
		return
	}

	result := context.Context.Rebuild()
	if len(result.Errors) > 0 {
		// Log the errors
		fmt.Println(result.Errors)
		os.Exit(1)
	}

	fmt.Printf("#### START ####\n")

	fmt.Printf("Filename: %s (output: %d)\n", context.Filename, len(result.OutputFiles))

	for i := range result.OutputFiles {
		outputFile := result.OutputFiles[i]
		fmt.Printf("------------\n")
		fmt.Printf("Output file: %s\n", outputFile)
		fmt.Printf("Path: %s\n", outputFile.Path)
		fmt.Printf("Contents: %s\n", outputFile.Contents)

		// Write the output to a file
		err := os.WriteFile(outputFile.Path, outputFile.Contents, 0644)
		if err != nil {
			// Log the error
			fmt.Println(err)
			os.Exit(1)
		}
	}

	fmt.Printf("#### DONE ####\n")
}

//export RemoveContext
func RemoveContext(id C.int) {
	mutex.Lock()
	defer mutex.Unlock()

	// Dispose of the ESBuild context to free up resources
	context, exists := contexts[int(id)]
	if !exists {
		fmt.Printf("Context with ID %d does not exist\n", id)
		return
	}

	context.Context.Dispose()
	delete(contexts, int(id))
}

func main() {}
