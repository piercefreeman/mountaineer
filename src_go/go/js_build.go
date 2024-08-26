package main

import (
	"fmt"
	"os"
	"sync"
	"unsafe"

	"github.com/evanw/esbuild/pkg/api"
)

// #include <stdint.h>
//
// extern void rust_callback(int32_t);
import "C"

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
	rawNodeModulesPath *C.char,
	rawEnvironment *C.char,
	liveReloadPort C.int,
	isSSR C.int,
) (returnId C.int, returnError *C.char) {
	/*
	 * liveReloadPort: 0 for no live reload
	 */
	mutex.Lock()
	defer mutex.Unlock()

	filename := C.GoString(rawFilename)
	nodeModulesPath := C.GoString(rawNodeModulesPath)
	environment := C.GoString(rawEnvironment)

	// If we already have the filename registered, return
	// the existing context ID.
	for id, context := range contexts {
		if context.Filename == filename {
			return C.int(id), nil
		}
	}

	buildOptions := api.BuildOptions{
		EntryPoints: []string{filename},
		Bundle:      true,
		Outfile:     filename + ".out",
		Sourcemap:   api.SourceMapExternal,
		Loader: map[string]api.Loader{
			".tsx": api.LoaderTSX,
			".jsx": api.LoaderJSX,
		},
		Define: map[string]string{
			"process.env.NODE_ENV":         fmt.Sprintf("\"%s\"", environment),
			"process.env.LIVE_RELOAD_PORT": fmt.Sprintf("%d", liveReloadPort),
		},
		NodePaths: []string{nodeModulesPath},
	}

	if isSSR == 1 {
		buildOptions.GlobalName = "SSR"
		buildOptions.Format = api.FormatIIFE
		buildOptions.Define["process.env.SSR_RENDERING"] = "true"
		buildOptions.Define["global"] = "window"
	} else {
		buildOptions.Format = api.FormatESModule
		buildOptions.Define["process.env.SSR_RENDERING"] = "false"
	}

	// Split code into least common parts
	// During a production build we will do this at the aggregate level
	// to ensure that the code is as small as possible; at debugging
	// we mostly want to keep local units isolate
	// buildOptions.Splitting = true

	ctx, err := api.Context(buildOptions)
	if err != nil {
		// Log the error
		fmt.Println(err)
		return -1, C.CString(err.Error())
	}

	id := nextID
	nextID++
	contexts[id] = &ESBuildContext{
		Filename: filename,
		Context:  ctx,
	}
	return C.int(id), nil
}

//export RebuildContext
func RebuildContext(id C.int) (returnError *C.char) {
	mutex.Lock()

	context, exists := contexts[int(id)]
	if !exists {
		fmt.Printf("Context with ID %d does not exist\n", id)
		mutex.Unlock()
		return
	}
	mutex.Unlock()

	result := context.Context.Rebuild()
	if len(result.Errors) > 0 {
		errorString := fmt.Sprintf("Error rebuilding %s:\n\n", context.Filename)
		for _, err := range result.Errors {
			errorString += ParseErrorLocation(err.Location)
			errorString += fmt.Sprintf("%s\n\n", err.Text)
		}
		return C.CString(errorString)
	}

	// The internal API doesn't write these to disk, so we need to do it ourselves
	for i := range result.OutputFiles {
		outputFile := result.OutputFiles[i]
		// Write the output to a file
		err := os.WriteFile(outputFile.Path, outputFile.Contents, 0644)
		if err != nil {
			// Log the error
			fmt.Println(err)
			return C.CString(err.Error())
		}
	}

	return nil
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

//export BundleAll
func BundleAll(
	paths **C.char,
	pathCount C.int,
	nodeModulesPath *C.char,
	environment *C.char,
	minified C.int,
	outdir *C.char,
) (returnError *C.char) {
	/*
	 * No context required, does an adhoc rebuild of all of the requested client
	 * files into a production bundle.
	 */
	// Convert C array of strings to Go slice
	goPaths := make([]string, int(pathCount))
	for i := 0; i < int(pathCount); i++ {
		goPaths[i] = C.GoString(*paths)
		paths = (**C.char)(unsafe.Pointer(uintptr(unsafe.Pointer(paths)) + unsafe.Sizeof(*paths)))
	}
	goNodeModulesPath := C.GoString(nodeModulesPath)
	goEnvironment := C.GoString(environment)
	goOutdir := C.GoString(outdir)
	goMinify := minified == 1

	buildOptions := api.BuildOptions{
		EntryPoints:       goPaths,
		Bundle:            true,
		Outdir:            goOutdir,
		Format:            api.FormatESModule,
		Splitting:         true,
		Sourcemap:         api.SourceMapExternal,
		MinifySyntax:      goMinify,
		MinifyWhitespace:  goMinify,
		MinifyIdentifiers: goMinify,
		Loader: map[string]api.Loader{
			".tsx": api.LoaderTSX,
			".jsx": api.LoaderJSX,
		},
		Define: map[string]string{
			// Assume we're building for a production, client-side use case
			"process.env.NODE_ENV":         fmt.Sprintf("\"%s\"", goEnvironment),
			"process.env.LIVE_RELOAD_PORT": "0",
			"process.env.SSR_RENDERING":    "false",
		},
		NodePaths: []string{goNodeModulesPath},
	}
	result := api.Build(buildOptions)
	if len(result.Errors) > 0 {
		errorMsg := fmt.Sprintf("Error executing esbuild: %v", result.Errors)
		return C.CString(errorMsg)
	}

	for i := range result.OutputFiles {
		outputFile := result.OutputFiles[i]
		err := os.WriteFile(outputFile.Path, outputFile.Contents, 0644)
		if err != nil {
			fmt.Println(err)
			return C.CString(err.Error())
		}
	}

	return nil
}

func ParseErrorLocation(loc *api.Location) string {
	errorMsg := fmt.Sprintf("Error in file '%s'", loc.File)
	if loc.Namespace != "" {
		errorMsg += fmt.Sprintf(", namespace '%s'", loc.Namespace)
	}
	errorMsg += fmt.Sprintf(" at line %d, column %d:\n", loc.Line, loc.Column+1) // Adjust column to be 1-based for readability

	// Append the line text and underline the error part if Length > 0.
	if loc.Length > 0 && loc.Column+loc.Length <= len(loc.LineText) {
		// Ensure proper handling of multi-byte characters.
		runes := []rune(loc.LineText)
		underline := make([]rune, len(runes))
		for i := range underline {
			if i >= loc.Column && i < loc.Column+loc.Length {
				underline[i] = '^'
			} else {
				underline[i] = ' '
			}
		}
		errorMsg += fmt.Sprintf("%s\n%s\n", string(runes), string(underline))
	} else {
		// Just append the line text if Length is not usable.
		errorMsg += loc.LineText + "\n"
	}

	if loc.Suggestion != "" {
		errorMsg += fmt.Sprintf("Suggestion: %s\n", loc.Suggestion)
	}

	return errorMsg
}

func main() {}
