Class iristool.GlobalTransfer Extends %RegisteredObject
{

ClassMethod Fail(message As %String) [ Private ]
{
    Throw ##class(%Exception.General).%New(message)
}

ClassMethod Name(value As %String) As %String [ Private ]
{
    If $Extract(value)="^" { Set value=$Extract(value,2,*) }
    If value'?1(1A,1"%").(1AN,1".") {
        Do ..Fail("Expected a single unsubscripted global name")
    }
    Quit value
}

/// Resolve in the connection namespace. A subscript is supplied in native
/// GetGlobalDest syntax, for example "east",1 including the string quotes.
ClassMethod ResolveGlobal(global As %String, subscript As %String = "") As %String
{
    Set name=..Name(global)
    Set result={},result.namespace=$Namespace,result.global=name
    Set result.destination=##class(%SYS.Namespace).GetGlobalDest($Namespace,name,subscript)
    Set result.defaultDestination=##class(%SYS.Namespace).GetGlobalDest($Namespace)
    Set result.mappings=[],result.exists=0,result.subscriptMapped=0
    Set rows=##class(%ResultSet).%New("%SYS.GlobalQuery:NameSpaceList")
    $$$ThrowOnError(rows.Execute($Namespace,name,1))
    While rows.Next(.sc) {
        Set item={},item.name=rows.Data("Name"),item.location=rows.Data("Location")
        Do result.mappings.%Push(item)
        If rows.Data("HasData") { Set result.exists=1 }
        If rows.Data("HasSubscripts") || (item.name["(") { Set result.subscriptMapped=1 }
    }
    $$$ThrowOnError(sc)
    Quit result.%ToJSON()
}

/// Format 0 selects block (7) or ISM (5) for the entire selection.
ClassMethod ExportTemp(names As %String, format As %Integer = 0, records As %String = "V", translation As %String = "") As %String
{
    If ",0,1,3,4,5,6,7,"'[(","_format_",") { Do ..Fail("Unknown export format") }
    If (records'="V") && (records'="S") { Do ..Fail("Expected record format V or S") }
    Set selected="",mapped=0
    For i=1:1:$Length(names,",") {
        Set name=..Name($Piece(names,",",i))
        Set info=##class(%DynamicObject).%FromJSON(..ResolveGlobal(name))
        If 'info.exists { Do ..Fail("Missing or inaccessible global: "_name) }
        If info.subscriptMapped || (info.destination'=info.defaultDestination) {
            Set mapped=1
            If format=7 { Do ..Fail("Block format cannot export mapped global: "_name) }
        }
        Set selected=selected_$Select(i=1:"",1:",")_name
    }
    If format=0 { Set format=$Select(mapped:5,1:7) }
    Set temp=##class(%File).TempFilename("gof")
    Try {
        $$$ThrowOnError(##class(%Library.Global).Export($Namespace,selected,temp,format,records,"-d",translation,.skipped))
        If $Get(skipped)'="" || ($Data(skipped)>1) { Do ..Fail("IRIS skipped globals during export") }
    } Catch err {
        Do ##class(%File).Delete(temp)
        Throw err
    }
    Set result={},result.path=temp,result.format=format
    Quit result.%ToJSON()
}

ClassMethod ExportGlobals(names As %String, file As %String, format As %Integer = 0, records As %String = "V", translation As %String = "") As %Integer
{
    If ##class(%File).Exists(file) { Do ..Fail("Output file already exists") }
    Set result=##class(%DynamicObject).%FromJSON(..ExportTemp(names,format,records,translation))
    Try {
        If '##class(%File).CopyFile(result.path,file,0) { Do ..Fail("Could not create output file") }
    } Catch err {
        Do ##class(%File).Delete(result.path)
        Throw err
    }
    Do ##class(%File).Delete(result.path)
    Quit result.format
}

/// IRIS detects native format from its header. A selective import is safe
/// only for block input; other formats ignore the selection.
ClassMethod ImportGlobals(file As %String, names As %String = "*", format As %Integer = 5, records As %String = "V") As %Integer
{
    If ",1,3,4,5,6,7,"'[(","_format_",") { Do ..Fail("Unknown import format") }
    If (records'="V") && (records'="S") { Do ..Fail("Expected record format V or S") }
    If names'="*" {
        For i=1:1:$Length(names,",") { Set name=..Name($Piece(names,",",i)) }
        Set stream=##class(%Stream.FileBinary).%New()
        $$$ThrowOnError(stream.LinkToFile(file))
        Set header=stream.Read(10,.sc)
        $$$ThrowOnError(sc)
        If header'=($Char(6,0,0,0)_"~%GOF~") { Do ..Fail("Selective import requires a native block file") }
        Set stream=""
    }
    $$$ThrowOnError(##class(%Library.Global).Import($Namespace,names,file,format,records="V"))
    Quit 1
}
}
